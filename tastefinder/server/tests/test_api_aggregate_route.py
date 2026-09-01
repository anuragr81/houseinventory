"""
tests/test_api_aggregate_route.py
----------------------------------
`GET /communities/{slug}/places/{place_id}/aggregate`.

The first route that reads a `CommunityAggregate` at all, so the first place
`PrivacyGate` is exercised over HTTP. Covers the published case, and
`INV-EXPOSE-3` (a below-threshold slice and an absent one must be
byte-identical) and `INV-EXPOSE-2` (no exact `cohort_size` on the wire).

`get_bucketing` is overridden alongside `get_session`, the same way
`get_catalogue` is overridden in `test_api_read_routes.py`: this suite proves
the route, not that `COHORT_BUCKETING_BOUNDARIES` happens to be set.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_bucketing, get_session
from app.domain.enums import CommunityStatus, FacetValueType
from app.domain.models import CohortBucketing, Community, CommunityAggregate, Facet, FacetStat
from app.main import create_app
from app.persistence.repositories import (
    AggregateRepository,
    CommunityRepository,
    FacetRepository,
    PlaceRefRepository,
)
from app.persistence.session import build_engine, build_session_factory, transaction
from app.persistence.tables import Base

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
BUCKETING = CohortBucketing(boundaries=(0, 10, 25, 50, 100))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    # See test_api_read_routes.py's client fixture for why this is a closure
    # rather than a lambda: FastAPI needs a generator *function* to know an
    # override requires teardown.
    def override_get_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_bucketing] = lambda: BUCKETING
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _found(factory: sessionmaker[Session], slug: str, *, threshold: int = 10) -> tuple[UUID, UUID]:
    """A minimal community plus one facet, written directly rather than
    through founding -- this suite is about the read route, not the founding
    bar. Returns (community_id, facet_id): `facet_stat.facet_id` carries a
    foreign key to `facet`, so an aggregate needs a real one to point at."""
    with transaction(factory) as session:
        CommunityRepository(session).add(
            Community(
                slug=slug,
                min_cohort_threshold=threshold,
                status=CommunityStatus.LIVE,
                created_at=NOW,
            )
        )
    with transaction(factory) as session:
        community = CommunityRepository(session).get_by_slug(slug)
        assert community is not None
        facet = Facet(
            community_id=community.community_id,
            name="Body",
            value_type=FacetValueType.NUMERIC,
            scale_min=0.0,
            scale_max=10.0,
        )
        FacetRepository(session).add_all([facet])
        return community.community_id, facet.facet_id


def _add_aggregate(
    factory: sessionmaker[Session],
    community_id: UUID,
    facet_id: UUID,
    place_id: str,
    *,
    cohort_size: int,
) -> None:
    """`place_id` carries a foreign key to `place_ref`, so a reference has to
    exist first -- irrelevant to what this route does, but required by the
    schema either way."""
    with transaction(factory) as session:
        PlaceRefRepository(session).ensure(place_id, NOW)
    with transaction(factory) as session:
        AggregateRepository(session).add(
            CommunityAggregate(
                community_id=community_id,
                place_id=place_id,
                facet_stats={
                    facet_id: FacetStat(facet_id=facet_id, mean=4.0, variance=1.0, n=cohort_size)
                },
                cohort_size=cohort_size,
                last_updated_at=NOW,
            )
        )


def test_a_published_aggregate_is_served(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    community_id, facet_id = _found(factory, "wine")
    _add_aggregate(factory, community_id, facet_id, "place-1", cohort_size=40)

    response = client.get("/communities/wine/places/place-1/aggregate")

    assert response.status_code == 200
    body = response.json()
    assert body["place_id"] == "place-1"
    assert body["cohort_size_bucket"] == "25-49"
    assert len(body["facet_summaries"]) == 1
    assert body["facet_summaries"][0]["mean"] == 4.0


def test_INV_EXPOSE_2_the_response_never_carries_an_exact_cohort_size(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    community_id, facet_id = _found(factory, "wine")
    _add_aggregate(factory, community_id, facet_id, "place-1", cohort_size=40)

    body = client.get("/communities/wine/places/place-1/aggregate").json()

    assert "cohort_size" not in body
    assert 40 not in body.values()


def test_INV_EXPOSE_3_below_threshold_and_absent_are_byte_identical(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    community_id, facet_id = _found(factory, "wine", threshold=10)
    _add_aggregate(factory, community_id, facet_id, "thin-place", cohort_size=3)

    suppressed = client.get("/communities/wine/places/thin-place/aggregate")
    absent = client.get("/communities/wine/places/never-rated/aggregate")

    assert suppressed.status_code == absent.status_code == 404
    assert suppressed.headers["content-type"] == absent.headers["content-type"]
    assert suppressed.json() == absent.json()


def test_INV_EXPOSE_4_a_cohort_of_exactly_the_threshold_is_published(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """Boundary case: >= threshold publishes, one below does not."""
    community_id, facet_id = _found(factory, "wine", threshold=10)
    _add_aggregate(factory, community_id, facet_id, "at-threshold", cohort_size=10)
    _add_aggregate(factory, community_id, facet_id, "one-below", cohort_size=9)

    at_threshold = client.get("/communities/wine/places/at-threshold/aggregate")
    one_below = client.get("/communities/wine/places/one-below/aggregate")

    assert at_threshold.status_code == 200
    assert one_below.status_code == 404


def test_unknown_community_404s(client: TestClient) -> None:
    response = client.get("/communities/does-not-exist/places/place-1/aggregate")
    assert response.status_code == 404


def test_a_seeding_community_with_no_rated_places_404s(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """A community can exist and be visible with nothing published yet --
    docs/03_API_CONTRACT.md: SEEDING means no aggregates, not hidden."""
    _found(factory, "wine")
    response = client.get("/communities/wine/places/never-rated/aggregate")
    assert response.status_code == 404
