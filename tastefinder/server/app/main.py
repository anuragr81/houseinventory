"""
app/main.py
-----------
FastAPI application factory.

Read-only routes only, per `docs/03_API_CONTRACT.md`: `GET /facets`,
`GET /communities`, `GET /communities/{slug}`, alongside `/health`.
`POST /communities` is not wired here -- it needs a way to verify five
authorisations belong to five distinct users, and authentication is
deliberately unbuilt (`docs/00_BOOTSTRAP.md`'s exclusion list). See
`app/services/community_founding.py` for the decision logic that route will
eventually call.
"""

from fastapi import FastAPI

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

    return app


app = create_app()
