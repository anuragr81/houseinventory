"""
app/persistence/repositories.py
-------------------------------
Reading and writing the persisted entities, in domain-model terms.

Repositories take and return the Pydantic models from `app.domain.models`,
never SQLAlchemy rows. The mapping lives here so that the domain layer stays
ignorant of the database and the services above it keep working on plain
objects, as they already do.

Scope is deliberately what founding and sign-in need: users, identity links,
sessions, communities, facets, memberships, place references, and
aggregates. `ConsentRecord` and `GoogleImportJob` have no repository yet --
consent is append-only (`INV-CONSENT-2`) and that enforcement deserves its
own pass rather than being tacked onto this one.

Nothing here queries `PlaceRef` by anything but an exact `place_id`, and
nothing returns a collection of them (`INV-CACHE-3`). Nothing here is indexed
by `user_id` over rating data (`INV-RAW-2`); membership by user is a different
thing and is both allowed and necessary.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import (
    AuthSession,
    Community,
    CommunityAggregate,
    CommunityMembership,
    Facet,
    FacetStat,
    IdentityLink,
    PlaceRef,
    User,
)
from app.persistence.tables import (
    CommunityAggregateTable,
    CommunityMembershipTable,
    CommunityTable,
    FacetStatTable,
    FacetTable,
    IdentityLinkTable,
    PlaceRefTable,
    SessionTokenTable,
    UserTable,
)


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> None:
        self._session.add(UserTable(user_id=user.user_id, created_at=user.created_at))

    def get(self, user_id: UUID) -> User | None:
        row = self._session.get(UserTable, user_id)
        if row is None:
            return None
        return User(user_id=row.user_id, created_at=row.created_at)

    def existing_ids(self, user_ids: Sequence[UUID]) -> set[UUID]:
        """Which of these users exist. Used to fail a write with a readable
        message rather than an opaque foreign-key violation."""
        if not user_ids:
            return set()
        rows = self._session.scalars(
            select(UserTable.user_id).where(UserTable.user_id.in_(user_ids))
        )
        return set(rows)


class IdentityLinkRepository:
    """`INV-AUTH-1`: never joined to rating data, and no lookup here takes
    anything but the digest -- there is no method that takes a raw `sub`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, link: IdentityLink) -> None:
        self._session.add(
            IdentityLinkTable(
                subject_hash=link.subject_hash,
                user_id=link.user_id,
                created_at=link.created_at,
            )
        )

    def get_user_id(self, subject_hash: str) -> UUID | None:
        row = self._session.get(IdentityLinkTable, subject_hash)
        return row.user_id if row is not None else None


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, auth_session: AuthSession) -> None:
        self._session.add(
            SessionTokenTable(
                token_hash=auth_session.token_hash,
                user_id=auth_session.user_id,
                created_at=auth_session.created_at,
                expires_at=auth_session.expires_at,
            )
        )

    def user_id_for_token(self, token_hash: str, now: datetime) -> UUID | None:
        """The session's owner, or `None` if the token is unknown or expired.

        One function whose output is already identical for "no such token"
        and "token existed, but has expired" -- deliberately, the same
        reasoning `PrivacyGate.suppress_if_below_threshold` gives for folding
        absent and suppressed into one return value: a caller that branches
        on which case it was risks telling them apart in a response, and
        there is no reason a client needs to.
        """
        row = self._session.get(SessionTokenTable, token_hash)
        if row is None or row.expires_at <= now:
            return None
        return row.user_id


class CommunityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, community: Community) -> None:
        self._session.add(
            CommunityTable(
                community_id=community.community_id,
                slug=community.slug,
                min_cohort_threshold=community.min_cohort_threshold,
                status=community.status,
                created_at=community.created_at,
            )
        )

    def get_by_slug(self, slug: str) -> Community | None:
        row = self._session.scalar(
            select(CommunityTable).where(CommunityTable.slug == slug)
        )
        if row is None:
            return None
        return self._to_domain(row)

    def list_all(self) -> list[Community]:
        """Every community, for `GET /communities`.

        No pagination yet: fine at the scale a handful of five-person
        foundings produce, wrong once this list is worth paginating, and
        nothing here promises otherwise.
        """
        rows = self._session.scalars(select(CommunityTable))
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: CommunityTable) -> Community:
        return Community(
            community_id=row.community_id,
            slug=row.slug,
            min_cohort_threshold=row.min_cohort_threshold,
            status=row.status,
            created_at=row.created_at,
        )


class FacetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, facets: Sequence[Facet]) -> None:
        self._session.add_all(
            FacetTable(
                facet_id=facet.facet_id,
                community_id=facet.community_id,
                name=facet.name,
                value_type=facet.value_type,
                scale_min=facet.scale_min,
                scale_max=facet.scale_max,
            )
            for facet in facets
        )

    def ids_for_community(self, community_id: UUID) -> set[UUID]:
        rows = self._session.scalars(
            select(FacetTable.facet_id).where(FacetTable.community_id == community_id)
        )
        return set(rows)

    def for_community(self, community_id: UUID) -> list[Facet]:
        """A community's facets, for `GET /communities/{slug}`."""
        rows = self._session.scalars(
            select(FacetTable).where(FacetTable.community_id == community_id)
        )
        return [
            Facet(
                facet_id=row.facet_id,
                community_id=row.community_id,
                name=row.name,
                value_type=row.value_type,
                scale_min=row.scale_min,
                scale_max=row.scale_max,
            )
            for row in rows
        ]


class MembershipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, memberships: Sequence[CommunityMembership]) -> None:
        self._session.add_all(
            CommunityMembershipTable(
                membership_id=membership.membership_id,
                user_id=membership.user_id,
                community_id=membership.community_id,
                tier=membership.tier,
                joined_at=membership.joined_at,
            )
            for membership in memberships
        )


class PlaceRefRepository:
    """Pointers into Google's catalogue. Addressable by exact id only.

    There is deliberately no method here that lists, searches, or filters
    place references by name, text, or geography -- that would be the derived
    venue catalogue `INV-CACHE-3` forbids.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, place_id: str) -> PlaceRef | None:
        row = self._session.get(PlaceRefTable, place_id)
        if row is None:
            return None
        return PlaceRef(
            place_id=row.place_id,
            last_refreshed_at=row.last_refreshed_at,
            cached_lat=row.cached_lat,
            cached_lng=row.cached_lng,
            coords_cached_at=row.coords_cached_at,
        )

    def ensure(self, place_id: str, now: datetime) -> None:
        """Record the id if it is not already known, with no cached coordinates.

        Coordinates are fetched live and cached separately for a bounded
        period (`INV-CACHE-1`); a reference created here holds the id alone,
        which is the only field that may be kept indefinitely.
        """
        if self._session.get(PlaceRefTable, place_id) is None:
            self._session.add(
                PlaceRefTable(place_id=place_id, last_refreshed_at=now)
            )


class AggregateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, aggregate: CommunityAggregate) -> None:
        """Insert a new aggregate and its facet statistics.

        Insert only. Updating a running aggregate in place is what the
        contribution path will need, and it is not built here because nothing
        calls it yet -- founding only ever creates.
        """
        self._session.add(
            CommunityAggregateTable(
                aggregate_id=aggregate.aggregate_id,
                community_id=aggregate.community_id,
                place_id=aggregate.place_id,
                cohort_size=aggregate.cohort_size,
                last_updated_at=aggregate.last_updated_at,
                noise_epsilon=aggregate.noise_epsilon,
                facet_stats=[
                    FacetStatTable(
                        aggregate_id=aggregate.aggregate_id,
                        facet_id=stat.facet_id,
                        mean=stat.mean,
                        variance=stat.variance,
                        n=stat.n,
                    )
                    for stat in aggregate.facet_stats.values()
                ],
            )
        )

    def get(self, community_id: UUID, place_id: str) -> CommunityAggregate | None:
        row = self._session.scalar(
            select(CommunityAggregateTable).where(
                CommunityAggregateTable.community_id == community_id,
                CommunityAggregateTable.place_id == place_id,
            )
        )
        if row is None:
            return None
        return CommunityAggregate(
            aggregate_id=row.aggregate_id,
            community_id=row.community_id,
            place_id=row.place_id,
            facet_stats={
                stat.facet_id: FacetStat(
                    facet_id=stat.facet_id,
                    mean=stat.mean,
                    variance=stat.variance,
                    n=stat.n,
                )
                for stat in row.facet_stats
            },
            cohort_size=row.cohort_size,
            last_updated_at=row.last_updated_at,
            noise_epsilon=row.noise_epsilon,
        )
