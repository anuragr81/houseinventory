"""
app/main.py
-----------
FastAPI application factory.

Phase 1 scope: a health endpoint and nothing else. Routers, persistence, and
the privacy gate arrive in later phases -- see docs/00_BOOTSTRAP.md.
"""

from fastapi import FastAPI


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
        """Liveness probe. The only endpoint in scope for Phase 1."""
        return {"status": "ok"}

    return app


app = create_app()
