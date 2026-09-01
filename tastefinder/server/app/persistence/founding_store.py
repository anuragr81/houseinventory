"""
app/persistence/founding_store.py
---------------------------------
Writing a `FoundingResult` to the database, atomically.

`docs/03_API_CONTRACT.md` requires founding to be all-or-nothing: no partial
community, no orphaned membership, no half-built aggregate. That guarantee is
the surrounding transaction (`session.transaction`), not anything here -- this
function writes, and the caller's unit of work decides whether the writes
survive. It deliberately does not commit.

**Facets are written here too.** `facet_stat` carries a foreign key to
`facet`, so an aggregate's statistics cannot be stored unless the community's
facets exist -- and facets belong to a community that does not exist before
founding, so they cannot pre-exist either. `found_community` resolves them
from the platform catalogue and returns them on the result, which is why this
function has no facet validation of its own: an aggregate cannot reference a
facet the same founding did not create.
"""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.repositories import (
    AggregateRepository,
    CommunityRepository,
    FacetRepository,
    MembershipRepository,
    PlaceRefRepository,
    UserRepository,
)
from app.services.community_founding import FoundingResult


class FoundingStoreError(Exception):
    """A founding could not be written.

    Messages must not name a specific user, contribution, or facet score --
    the rule `docs/03_API_CONTRACT.md` sets for anything a route returns.
    """


class SlugAlreadyTakenError(FoundingStoreError):
    """Another community already holds this slug."""


class UnknownFounderError(FoundingStoreError):
    """A founding referenced an account that does not exist.

    Founding does not mint accounts. Creating a `User` as a side effect of
    someone else's request would be an identity decision, and identity is
    deliberately unbuilt (`docs/00_BOOTSTRAP.md`).
    """


def persist_founding(
    session: Session,
    result: FoundingResult,
    now: datetime,
) -> None:
    """Write a founding. Does not commit -- see the module docstring.

    Args:
        session: the unit of work. Roll it back and nothing here survives.
        result: what `community_founding.found_community` produced,
            including the facets it resolved from the catalogue.
        now: used for any `PlaceRef` rows created for venues not yet known.

    Raises:
        SlugAlreadyTakenError: the slug is in use.
        UnknownFounderError: a founder has no account.
    """
    community = result.community

    users = UserRepository(session)
    founder_ids = [membership.user_id for membership in result.memberships]
    missing = set(founder_ids) - users.existing_ids(founder_ids)
    if missing:
        raise UnknownFounderError(
            f"{len(missing)} of {len(founder_ids)} founders have no account."
        )

    CommunityRepository(session).add(community)
    try:
        # Flush here so a duplicate slug surfaces as an IntegrityError we can
        # name, while the transaction is still the caller's to roll back.
        session.flush()
    except IntegrityError as error:
        raise SlugAlreadyTakenError(
            f"A community already exists with the slug {community.slug!r}."
        ) from error

    FacetRepository(session).add_all(result.facets)
    MembershipRepository(session).add_all(result.memberships)

    places = PlaceRefRepository(session)
    aggregates = AggregateRepository(session)
    for place_id, aggregate in result.aggregates.items():
        places.ensure(place_id, now)
        session.flush()  # the aggregate's FK needs the place reference present
        aggregates.add(aggregate)

    session.flush()
