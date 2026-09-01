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

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import CommunityStatus, FacetValueType
from app.domain.models import Community, Facet, User
from app.persistence.founding_store import (
    MissingFacetError,
    SlugAlreadyTakenError,
    UnknownFounderError,
    persist_founding,
)
from app.persistence.repositories import (
    AggregateRepository,
    CommunityRepository,
    PlaceRefRepository,
    UserRepository,
)
from app.persistence.session import build_engine, build_session_factory, transaction
from app.persistence.tables import Base, CommunityMembershipTable, CommunityTable
from app.services.community_founding import FoundingContribution, found_community

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


def _facets(community_id: UUID, facet_ids: list[UUID]) -> list[Facet]:
    return [
        Facet(
            facet_id=facet_id,
            community_id=community_id,
            name=f"facet-{index}",
            value_type=FacetValueType.NUMERIC,
            scale_min=0.0,
            scale_max=10.0,
        )
        for index, facet_id in enumerate(facet_ids)
    ]


def _founding_batch(facet_id: UUID, count: int = 5) -> list[FoundingContribution]:
    return [
        FoundingContribution(
            user_id=uuid4(), place_id=f"place-{index}", facet_scores={facet_id: 4.0}
        )
        for index in range(count)
    ]


def _seed_users(factory: sessionmaker[Session], user_ids: list[UUID]) -> None:
    with transaction(factory) as session:
        users = UserRepository(session)
        for user_id in user_ids:
            users.add(User(user_id=user_id, created_at=NOW))


# ── The database actually enforces what the schema declares ───────────────────


def test_sqlite_foreign_keys_are_enforced(factory: sessionmaker[Session]) -> None:
    """Without PRAGMA foreign_keys=ON this silently succeeds -- see session.py."""
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
    facet_id = uuid4()
    batch = _founding_batch(facet_id)
    _seed_users(factory, [c.user_id for c in batch])
    result = found_community("wine", 10, batch, NOW)

    with transaction(factory) as session:
        persist_founding(
            session, result, _facets(result.community.community_id, [facet_id]), NOW
        )

    with transaction(factory) as session:
        assert CommunityRepository(session).get_by_slug("wine") is not None
        memberships = session.scalars(select(CommunityMembershipTable)).all()
        assert len(memberships) == 5
        assert all(m.tier == "FOUNDER" for m in memberships)

        aggregates = AggregateRepository(session)
        stored = aggregates.get(result.community.community_id, "place-0")
        assert stored is not None
        assert stored.cohort_size == 1
        assert stored.facet_stats[facet_id].mean == pytest.approx(4.0)


def test_a_duplicate_slug_is_refused(factory: sessionmaker[Session]) -> None:
    facet_id = uuid4()
    for attempt in range(2):
        batch = _founding_batch(facet_id)
        _seed_users(factory, [c.user_id for c in batch])
        result = found_community("wine", 10, batch, NOW)
        facets = _facets(result.community.community_id, [facet_id])

        if attempt == 0:
            with transaction(factory) as session:
                persist_founding(session, result, facets, NOW)
        else:
            with pytest.raises(SlugAlreadyTakenError), transaction(factory) as session:
                persist_founding(session, result, facets, NOW)


def test_a_founder_without_an_account_is_refused(
    factory: sessionmaker[Session],
) -> None:
    """Founding does not mint accounts."""
    facet_id = uuid4()
    batch = _founding_batch(facet_id)
    _seed_users(factory, [c.user_id for c in batch[:4]])  # one missing
    result = found_community("wine", 10, batch, NOW)

    with pytest.raises(UnknownFounderError), transaction(factory) as session:
        persist_founding(
            session, result, _facets(result.community.community_id, [facet_id]), NOW
        )


def test_a_scored_facet_the_community_does_not_define_is_refused(
    factory: sessionmaker[Session],
) -> None:
    facet_id = uuid4()
    batch = _founding_batch(facet_id)
    _seed_users(factory, [c.user_id for c in batch])
    result = found_community("wine", 10, batch, NOW)

    with pytest.raises(MissingFacetError), transaction(factory) as session:
        persist_founding(
            session,
            result,
            _facets(result.community.community_id, [uuid4()]),  # a different facet
            NOW,
        )


def test_facets_belonging_to_another_community_are_refused(
    factory: sessionmaker[Session],
) -> None:
    facet_id = uuid4()
    batch = _founding_batch(facet_id)
    _seed_users(factory, [c.user_id for c in batch])
    result = found_community("wine", 10, batch, NOW)

    with pytest.raises(MissingFacetError), transaction(factory) as session:
        persist_founding(session, result, _facets(uuid4(), [facet_id]), NOW)


def test_a_failed_founding_leaves_no_trace(factory: sessionmaker[Session]) -> None:
    """The atomicity docs/03_API_CONTRACT.md promises, against a real database."""
    facet_id = uuid4()
    batch = _founding_batch(facet_id)
    _seed_users(factory, [c.user_id for c in batch[:4]])
    result = found_community("wine", 10, batch, NOW)

    with pytest.raises(UnknownFounderError), transaction(factory) as session:
        persist_founding(
            session, result, _facets(result.community.community_id, [facet_id]), NOW
        )

    with transaction(factory) as session:
        assert CommunityRepository(session).get_by_slug("wine") is None
        assert session.scalars(select(CommunityMembershipTable)).all() == []
        assert PlaceRefRepository(session).get("place-0") is None


def test_no_aggregate_row_carries_a_user_reference(
    factory: sessionmaker[Session],
) -> None:
    """INV-RAW-2, asserted against what actually landed on disk."""
    facet_id = uuid4()
    batch = _founding_batch(facet_id)
    _seed_users(factory, [c.user_id for c in batch])
    result = found_community("wine", 10, batch, NOW)

    with transaction(factory) as session:
        persist_founding(
            session, result, _facets(result.community.community_id, [facet_id]), NOW
        )

    with transaction(factory) as session:
        stored = AggregateRepository(session).get(
            result.community.community_id, "place-0"
        )
    assert stored is not None
    assert "user_id" not in stored.model_dump()
