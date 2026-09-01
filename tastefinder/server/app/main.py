"""
app/main.py
-----------
FastAPI application factory.

Per `docs/03_API_CONTRACT.md`: `GET /facets`, `GET /communities`,
`GET /communities/{slug}`, `GET /communities/{slug}/places/{place_id}/aggregate`,
`POST /auth/google`, and `POST /communities`, alongside `/health`.

`POST /communities` is an ordinary authenticated request now that founding no
longer needs five distinct people -- see `app/services/community_founding.py`
for the decision logic and `app/api/communities.py` for the route. It needs a
session identifying the founder, which `POST /auth/google`
(`docs/05_AUTH_DESIGN.md`, Part 1) is what issues.
"""

from fastapi import FastAPI

from app.api.aggregates import router as aggregates_router
from app.api.auth import router as auth_router
from app.api.communities import router as communities_router
from app.api.facets import router as facets_router


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="Taste Platform",
        version="0.1.0",
        description=(
            "Preference-aggregation platform for narrow interest communities. "
            "The product is the aggregate, taste-weighted signal for a community, "
            "never an individual's profile or history."
        ),
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    app.include_router(facets_router)
    app.include_router(communities_router)
    app.include_router(aggregates_router)
    app.include_router(auth_router)

    return app


app = create_app()
