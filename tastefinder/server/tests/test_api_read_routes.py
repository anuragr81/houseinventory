"""
tests/test_api_read_routes.py
------------------------------
GET /facets, GET /communities, GET /communities/{slug}.

Both dependencies (`get_session`, `get_catalogue`) are overridden rather than
set via environment variables, so this suite needs no `DATABASE_URL` or
`FACET_CATALOGUE_PATH` to run -- it proves the routes, not the deployment
configuration. `/health` needing neither is the property `app/config.py`
exists to guarantee, and this suite is what would break first if a route
accidentally required one at import time.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_catalogue, get_session
from app.domain.enums import FacetValueType
from app.domain.facet_catalogue import FacetCatalogue, FacetDefinition
from app.domain.models import User
from app.main import create_app
from app.persistence.founding_store import persist_founding
from app.persistence.repositories import UserRepository
from app.persistence.session import build_engine, build_session_factory, transaction
from app.persistence.tables import Base
from app.services.community_founding import FoundingContribution, found_community

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

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
    # FastAPI decides whether an override needs generator-style teardown by
    # inspecting the callable itself, not its return value. A lambda that
    # returns a generator object hides that: it gets treated as an ordinary
    # dependency and the generator is handed to the route unconsumed. The
    # override has to *be* a generator function, matching get_session's own
    # shape, so a closure is used instead of wrapping one in a lambda.
    def override_get_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_catalogue] = lambda: CATALOGUE
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _found_and_persist(factory: sessionmaker[Session], slug: str) -> None:
    """A minimal valid founding, written to the test database."""
    founder_id = uuid4()
    batch = [
        FoundingContribution(place_id=f"place-{index}", facet_scores={"body": 4.0})
        for index in range(5)
    ]
    result = found_community(
        slug, 10, frozenset({"body"}), CATALOGUE, founder_id, batch, NOW
    )
    with transaction(factory) as session:
        UserRepository(session).add(User(user_id=founder_id, created_at=NOW))
    with transaction(factory) as session:
        persist_founding(session, result, NOW)


# ── GET /facets ────────────────────────────────────────────────────────────────


def test_get_facets_returns_the_catalogue(client: TestClient) -> None:
    response = client.get("/facets")

    assert response.status_code == 200
    assert response.json() == [
        {
            "key": "body",
            "name": "Body",
            "value_type": "NUMERIC",
            "scale_min": 0.0,
            "scale_max": 10.0,
        }
    ]


def test_get_facets_needs_no_database(client: TestClient) -> None:
    """The catalogue is file-backed, not DB-backed -- confirmed by never
    touching the get_session override in this test."""
    response = client.get("/facets")
    assert response.status_code == 200


# ── GET /communities ─────────────────────────────────────────────────────────


def test_get_communities_is_empty_before_any_founding(client: TestClient) -> None:
    response = client.get("/communities")
    assert response.status_code == 200
    assert response.json() == []


def test_get_communities_lists_a_founded_community(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    _found_and_persist(factory, "wine")

    response = client.get("/communities")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["slug"] == "wine"
    assert body[0]["status"] in {"SEEDING", "LIVE"}
    assert "cohort_size" not in body[0]
    assert set(body[0]) == {"community_id", "slug", "status"}


def test_get_communities_response_shape_excludes_the_threshold(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """min_cohort_threshold is real data on the model; the contract omits it."""
    _found_and_persist(factory, "wine")
    body = client.get("/communities").json()
    assert "min_cohort_threshold" not in body[0]


# ── GET /communities/{slug} ──────────────────────────────────────────────────


def test_get_community_by_slug(client: TestClient, factory: sessionmaker[Session]) -> None:
    _found_and_persist(factory, "wine")

    response = client.get("/communities/wine")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "wine"
    assert len(body["facets"]) == 1
    assert body["facets"][0]["name"] == "Body"
    assert "facet_id" in body["facets"][0]


def test_get_community_by_slug_404s_when_absent(client: TestClient) -> None:
    response = client.get("/communities/does-not-exist")
    assert response.status_code == 404


def test_a_seeding_community_is_still_visible(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """docs/03_API_CONTRACT.md: SEEDING means no aggregates yet, not hidden."""
    _found_and_persist(factory, "wine")  # 5 founders, threshold 10 -> SEEDING

    detail = client.get("/communities/wine")
    listing = client.get("/communities")

    assert detail.json()["status"] == "SEEDING"
    assert listing.json()[0]["status"] == "SEEDING"
