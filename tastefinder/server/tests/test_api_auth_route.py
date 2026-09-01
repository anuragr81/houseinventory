"""
tests/test_api_auth_route.py
------------------------------
`POST /auth/google`, `get_current_user_id`, and `POST /communities` end to
end: sign in over HTTP, use the returned bearer token to found a community.

`get_id_token_verifier` is overridden with a fake that maps a fixed string to
a `sub` (or raises), the same way `get_catalogue` and `get_bucketing` are
overridden elsewhere -- the real verifier is a network call to Google, and
this suite proves the route wiring, not Google's signing keys.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import (
    get_catalogue,
    get_id_token_verifier,
    get_identity_pepper,
    get_session,
)
from app.domain.enums import FacetValueType
from app.domain.facet_catalogue import FacetCatalogue, FacetDefinition
from app.main import create_app
from app.persistence.session import build_engine, build_session_factory
from app.persistence.tables import Base
from app.services.auth import InvalidIdTokenError

PEPPER = "test-pepper-do-not-use-in-production"

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


class FakeVerifier:
    """Maps a fixed set of "id tokens" to Google `sub` claims, no network."""

    def __init__(self, subs_by_token: dict[str, str]) -> None:
        self._subs_by_token = subs_by_token

    def verify(self, id_token: str) -> str:
        sub = self._subs_by_token.get(id_token)
        if sub is None:
            raise InvalidIdTokenError("unknown test token")
        return sub


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
    def override_get_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_catalogue] = lambda: CATALOGUE
    app.dependency_overrides[get_identity_pepper] = lambda: PEPPER
    app.dependency_overrides[get_id_token_verifier] = lambda: FakeVerifier(
        {"valid-token-for-alice": "google-sub-alice", "valid-token-for-bob": "google-sub-bob"}
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _founding_payload(slug: str) -> dict[str, object]:
    return {
        "slug": slug,
        "min_cohort_threshold": 10,
        "facet_keys": ["body"],
        "contributions": [
            {"place_id": f"place-{i}", "facet_scores": {"body": 4.0}} for i in range(5)
        ],
    }


# ── POST /auth/google ─────────────────────────────────────────────────────────


def test_a_valid_id_token_returns_a_session(client: TestClient) -> None:
    response = client.post("/auth/google", json={"id_token": "valid-token-for-alice"})

    assert response.status_code == 200
    body = response.json()
    assert "session_token" in body
    assert "expires_at" in body
    assert len(body["session_token"]) >= 32


def test_an_invalid_id_token_401s(client: TestClient) -> None:
    response = client.post("/auth/google", json={"id_token": "garbage"})
    assert response.status_code == 401


def test_signing_in_twice_with_the_same_identity_issues_two_usable_sessions(
    client: TestClient,
) -> None:
    """Same Google account, two devices: both sessions work independently."""
    first = client.post("/auth/google", json={"id_token": "valid-token-for-alice"})
    second = client.post("/auth/google", json={"id_token": "valid-token-for-alice"})

    assert first.json()["session_token"] != second.json()["session_token"]

    for token in (first.json()["session_token"], second.json()["session_token"]):
        response = client.post(
            "/communities",
            json=_founding_payload(f"wine-{token[:8]}"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201


# ── POST /communities, authenticated ─────────────────────────────────────────


def test_founding_without_a_session_401s(client: TestClient) -> None:
    response = client.post("/communities", json=_founding_payload("wine"))
    assert response.status_code == 401


def test_founding_with_a_garbage_bearer_token_401s(client: TestClient) -> None:
    response = client.post(
        "/communities",
        json=_founding_payload("wine"),
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


def test_a_signed_in_founder_can_found_a_community(client: TestClient) -> None:
    sign_in = client.post("/auth/google", json={"id_token": "valid-token-for-alice"})
    token = sign_in.json()["session_token"]

    response = client.post(
        "/communities",
        json=_founding_payload("wine"),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "wine"
    assert set(body) == {"community_id", "slug", "status"}

    # And it is visible through the ordinary read path afterwards.
    listed = client.get("/communities").json()
    assert any(entry["slug"] == "wine" for entry in listed)


def test_founding_with_too_few_venues_422s(client: TestClient) -> None:
    sign_in = client.post("/auth/google", json={"id_token": "valid-token-for-alice"})
    token = sign_in.json()["session_token"]
    payload = _founding_payload("wine")
    payload["contributions"] = payload["contributions"][:2]  # type: ignore[index]

    response = client.post(
        "/communities", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 422


def test_founding_a_taken_slug_409s(client: TestClient) -> None:
    sign_in = client.post("/auth/google", json={"id_token": "valid-token-for-alice"})
    alice_token = sign_in.json()["session_token"]
    client.post(
        "/communities",
        json=_founding_payload("wine"),
        headers={"Authorization": f"Bearer {alice_token}"},
    )

    bob = client.post("/auth/google", json={"id_token": "valid-token-for-bob"})
    bob_token = bob.json()["session_token"]

    response = client.post(
        "/communities",
        json=_founding_payload("wine"),
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert response.status_code == 409
