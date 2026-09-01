"""
tests/test_persistence_repositories.py
--------------------------------------
The repositories and the founding write, against a real SQLite database.

These run against a file-backed database created from `Base.metadata` rather
than a mock, because the things most worth checking here are the things a mock
would happily pretend about: that foreign keys are enforced, that a rolled-back
transaction leaves nothing behind, and that a duplicate slug is refused by the
database rather than by a hopeful check in Python.

SQLite, not PostgreSQL. The schema is written to serve both
(`docs/01_STACK_DECISIONS.md`) and the dialect-specific behaviour is not
exercised here -- so these tests prove the logic, not the dialect.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import DBAPIError, IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import CommunityStatus, FacetValueType
from app.domain.facet_catalogue import FacetCatalogue, FacetDefinition
from app.domain.models import Community, CommunityAggregate, User
from app.persistence.founding_store import (
    SlugAlreadyTakenError,
    UnknownFounderError,
    persist_founding,
)
from app.persistence.repositories import (
    AggregateRepository,
    CommunityRepository,
    FacetRepository,
    PlaceRefRepository,
    UserRepository,
)
from app.persistence.session import build_engine, build_session_factory, transaction
from app.persistence.tables import (
    Base,
    CommunityAggregateTable,
    CommunityMembershipTable,
    CommunityTable,
)
from app.services.community_founding import (
    FoundingContribution,
    FoundingResult,
    found_community,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

# Every dialect this project claims to support runs the whole suite below.
# Dialects disagree about things that look settled -- SQLite silently ignored
# foreign keys and dropped tzinfo, MySQL has no timezone-aware DATETIME at all
# -- and each of those was found by running real SQL, not by reading docs. A
# dialect that is not exercised here is one this project does not actually
# know works.
#
# TEST_MYSQL_URL is opt-in: set it to run the suite against MySQL as well.
# Unset, the MySQL parametrisation skips rather than fails, so a checkout with
# no database server still gets a full SQLite run.
MYSQL_URL = os.environ.get("TEST_MYSQL_URL")


@pytest.fixture(params=["sqlite", "mysql"])
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    if request.param == "sqlite":
        engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    else:
        if not MYSQL_URL:
            pytest.skip("TEST_MYSQL_URL not set; skipping the MySQL dialect run")
        engine = build_engine(MYSQL_URL)
        # A shared server keeps state between runs; the suite assumes a clean
        # schema, so drop before create rather than after, which also leaves
        # the tables inspectable when something fails.
        Base.metadata.drop_all(engine)

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


CATALOGUE = FacetCatalogue(
    definitions=(
        FacetDefinition(
            key="body",
            name="Body",
            value_type=FacetValueType.NUMERIC,
            scale_min=0.0,
            scale_max=10.0,
        ),
    )
)
FACET_KEYS = frozenset({"body"})


FOUNDER = uuid4()


def _founding_batch(count: int = 5) -> list[FoundingContribution]:
    return [
        FoundingContribution(place_id=f"place-{index}", facet_scores={"body": 4.0})
        for index in range(count)
    ]


def _found(
    batch: list[FoundingContribution],
    slug: str = "wine",
    founder_id: UUID = FOUNDER,
) -> FoundingResult:
    return found_community(slug, 10, FACET_KEYS, CATALOGUE, founder_id, batch, NOW)


def _seed_users(factory: sessionmaker[Session], user_ids: list[UUID]) -> None:
    with transaction(factory) as session:
        users = UserRepository(session)
        for user_id in user_ids:
            users.add(User(user_id=user_id, created_at=NOW))


# ── The database actually enforces what the schema declares ───────────────────


def test_foreign_keys_are_enforced(factory: sessionmaker[Session]) -> None:
    """SQLite needs PRAGMA foreign_keys=ON to do this at all -- see session.py.

    MySQL's InnoDB enforces them by default, so this passes there for free.
    Running it on both is the point: the guarantee is claimed for every
    dialect, so it is checked on every dialect.
    """
    with pytest.raises(IntegrityError), transaction(factory) as session:
        session.add(
            CommunityMembershipTable(
                membership_id=uuid4(),
                user_id=uuid4(),  # no such user
                community_id=uuid4(),  # no such community
                tier="FOUNDER",
                joined_at=NOW,
            )
        )


def test_a_rolled_back_transaction_leaves_nothing(
    factory: sessionmaker[Session],
) -> None:
    with pytest.raises(RuntimeError), transaction(factory) as session:
        UserRepository(session).add(User(user_id=uuid4(), created_at=NOW))
        raise RuntimeError("boom")

    with transaction(factory) as session:
        assert session.scalars(select(CommunityTable)).all() == []


# ── Round-tripping through the repositories ───────────────────────────────────


def test_user_round_trip(factory: sessionmaker[Session]) -> None:
    user_id = uuid4()
    _seed_users(factory, [user_id])

    with transaction(factory) as session:
        stored = UserRepository(session).get(user_id)

    assert stored is not None
    assert stored.user_id == user_id
    assert stored.created_at == NOW


def test_unknown_user_reads_as_none(factory: sessionmaker[Session]) -> None:
    with transaction(factory) as session:
        assert UserRepository(session).get(uuid4()) is None


def test_community_round_trip_by_slug(factory: sessionmaker[Session]) -> None:
    community = Community(
        slug="wine",
        min_cohort_threshold=10,
        status=CommunityStatus.SEEDING,
        created_at=NOW,
    )
    with transaction(factory) as session:
        CommunityRepository(session).add(community)

    with transaction(factory) as session:
        stored = CommunityRepository(session).get_by_slug("wine")

    assert stored is not None
    assert stored.community_id == community.community_id
    assert stored.min_cohort_threshold == 10


def test_place_ref_is_created_once_and_holds_no_coordinates(
    factory: sessionmaker[Session],
) -> None:
    with transaction(factory) as session:
        places = PlaceRefRepository(session)
        places.ensure("place-1", NOW)
        session.flush()
        places.ensure("place-1", NOW)

    with transaction(factory) as session:
        stored = PlaceRefRepository(session).get("place-1")

    assert stored is not None
    assert stored.cached_lat is None
    assert stored.cached_lng is None
    assert stored.coords_cached_at is None


# ── Founding, written whole ───────────────────────────────────────────────────


def test_a_founding_is_persisted_in_full(factory: sessionmaker[Session]) -> None:
    batch = _founding_batch()
    _seed_users(factory, [FOUNDER])
    result = _found(batch)

    with transaction(factory) as session:
        persist_founding(session, result, NOW)

    with transaction(factory) as session:
        assert CommunityRepository(session).get_by_slug("wine") is not None
        memberships = session.scalars(select(CommunityMembershipTable)).all()
        assert len(memberships) == 1
        assert all(m.tier == "FOUNDER" for m in memberships)

        aggregates = AggregateRepository(session)
        stored = aggregates.get(result.community.community_id, "place-0")
        assert stored is not None
        assert stored.cohort_size == 1
        assert stored.facet_stats[result.facets[0].facet_id].mean == pytest.approx(4.0)


def test_a_duplicate_slug_is_refused(factory: sessionmaker[Session]) -> None:
    _seed_users(factory, [FOUNDER])  # once: the founder is the same account both times

    for attempt in range(2):
        batch = _founding_batch()
        result = _found(batch)

        if attempt == 0:
            with transaction(factory) as session:
                persist_founding(session, result, NOW)
        else:
            with pytest.raises(SlugAlreadyTakenError), transaction(factory) as session:
                persist_founding(session, result, NOW)


def test_a_founder_without_an_account_is_refused(
    factory: sessionmaker[Session],
) -> None:
    """Founding does not mint accounts."""
    batch = _founding_batch()
    # The founder's account deliberately not created.
    result = _found(batch)

    with pytest.raises(UnknownFounderError), transaction(factory) as session:
        persist_founding(session, result, NOW)


def test_the_facets_a_founding_selected_are_written(
    factory: sessionmaker[Session],
) -> None:
    """An aggregate cannot reference a facet its own founding did not create.

    The facets come from the FoundingResult rather than being passed in
    alongside it, so the mismatch this used to guard against is not
    reachable -- the equivalent check now lives at the service layer, where a
    contribution scoring an unselected facet is refused.
    """
    batch = _founding_batch()
    _seed_users(factory, [FOUNDER])
    result = _found(batch)

    with transaction(factory) as session:
        persist_founding(session, result, NOW)

    with transaction(factory) as session:
        stored = FacetRepository(session).ids_for_community(
            result.community.community_id
        )
    assert stored == {facet.facet_id for facet in result.facets}


def test_a_failed_founding_leaves_no_trace(factory: sessionmaker[Session]) -> None:
    """The atomicity docs/03_API_CONTRACT.md promises, against a real database."""
    batch = _founding_batch()
    # The founder's account deliberately not created.
    result = _found(batch)

    with pytest.raises(UnknownFounderError), transaction(factory) as session:
        persist_founding(session, result, NOW)

    with transaction(factory) as session:
        assert CommunityRepository(session).get_by_slug("wine") is None
        assert session.scalars(select(CommunityMembershipTable)).all() == []
        assert PlaceRefRepository(session).get("place-0") is None


def test_no_aggregate_row_carries_a_user_reference(
    factory: sessionmaker[Session],
) -> None:
    """INV-RAW-2, asserted against what actually landed on disk."""
    batch = _founding_batch()
    _seed_users(factory, [FOUNDER])
    result = _found(batch)

    with transaction(factory) as session:
        persist_founding(session, result, NOW)

    with transaction(factory) as session:
        stored = AggregateRepository(session).get(
            result.community.community_id, "place-0"
        )
    assert stored is not None
    assert "user_id" not in stored.model_dump()


# ── Dialects disagreeing about things that look settled ───────────────────────


def test_a_non_utc_aware_datetime_round_trips_to_the_same_instant(
    factory: sessionmaker[Session],
) -> None:
    """The conversion UtcDateTime exists to make reliable.

    MySQL's DATETIME carries no offset and SQLite returns naive values, so
    without normalisation each dialect loses or mangles this differently.
    An input in a non-UTC zone is the case that actually distinguishes a
    working conversion from one that only looks right because the test data
    was already UTC.
    """
    india = timezone(timedelta(hours=5, minutes=30))
    local_noon_utc = datetime(2026, 9, 1, 17, 30, tzinfo=india)
    user_id = uuid4()

    with transaction(factory) as session:
        UserRepository(session).add(
            User(user_id=user_id, created_at=local_noon_utc)
        )

    with transaction(factory) as session:
        stored = UserRepository(session).get(user_id)

    assert stored is not None
    assert stored.created_at == local_noon_utc  # same instant
    assert stored.created_at == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert stored.created_at.tzinfo is not None


def test_a_naive_datetime_is_refused_rather_than_assumed_to_be_utc(
    factory: sessionmaker[Session],
) -> None:
    """Guessing a zone produces data that looks fine and is wrong."""
    # SQLAlchemy wraps a bind-time error from a TypeDecorator in
    # StatementError, so the ValueError arrives chained rather than raw.
    with pytest.raises(StatementError, match="Naive datetime"), transaction(
        factory
    ) as session:
        UserRepository(session).add(
            User(user_id=uuid4(), created_at=datetime(2026, 9, 1, 12, 0))
        )


def test_the_cohort_size_check_constraint_is_enforced(
    factory: sessionmaker[Session],
) -> None:
    """MySQL before 8.0.16 parsed CHECK constraints and silently ignored them.

    This asserts the database actually rejects a negative cohort size, which
    is why the same rule is *also* enforced on the domain model: an integrity
    rule only some dialects keep is not an integrity rule. See the comment on
    CommunityAggregate.cohort_size.
    """
    community_id = uuid4()
    with transaction(factory) as session:
        CommunityRepository(session).add(
            Community(
                community_id=community_id,
                slug="wine",
                min_cohort_threshold=10,
                status=CommunityStatus.SEEDING,
                created_at=NOW,
            )
        )
        PlaceRefRepository(session).ensure("place-x", NOW)

    with pytest.raises(DBAPIError), transaction(factory) as session:
        session.add(
            CommunityAggregateTable(
                aggregate_id=uuid4(),
                community_id=community_id,
                place_id="place-x",
                cohort_size=-5,
                last_updated_at=NOW,
            )
        )


def test_the_domain_model_refuses_a_negative_cohort_size() -> None:
    """The half that holds even where the database's CHECK does not."""
    with pytest.raises(ValidationError):
        CommunityAggregate(
            community_id=uuid4(),
            place_id="place-x",
            cohort_size=-1,
            last_updated_at=NOW,
        )
