"""
tests/test_health.py
--------------------
Phase 1 gate check: the health endpoint responds.
"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_200() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_ok_status() -> None:
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_health_is_the_only_route() -> None:
    """Phase 1 says /health "and nothing else" -- guard against scope creep."""
    app = create_app()
    # BaseRoute has no declared `path`; only concrete Route/APIRoute subclasses do.
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {p for p in paths if p.startswith("/health")} == {"/health"}
