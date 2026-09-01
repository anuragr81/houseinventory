"""
app/config.py
-------------
Environment-driven settings.

Every external dependency is read from the environment. Nothing here carries a
default that embeds a real value: an unset setting is None, and asking for one
that is required raises loudly rather than silently falling back.

See docs/00_BOOTSTRAP.md (Phase 1) and CLAUDE.md ("No secrets in the repo").
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Externally-supplied configuration.

    All fields are optional at import time so that the process can start and
    serve /health without a database or Google credentials -- there is no
    persistence and no external call at bootstrap. Use `require()` at the point
    of use to assert a setting is present, so the failure names the missing
    variable instead of surfacing as an obscure downstream error.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Persistence. SQLite locally and in tests, MySQL when deployed
    # (docs/01_STACK_DECISIONS.md); PostgreSQL is also supported.
    database_url: str | None = None

    # Path to a JSON file describing the platform's facet catalogue -- see
    # app/domain/facet_catalogue.py. No default and no fallback content:
    # which facets exist is product content the owner supplies, not something
    # to guess a plausible-looking value for.
    facet_catalogue_path: str | None = None

    # Comma-separated ascending lower bounds for CohortBucketing, e.g.
    # "0,10,25,50,100". No default: bucket width is a privacy parameter, the
    # same class of decision as min_cohort_threshold (OPEN-1) and the noise
    # parameters (OPEN-3) -- see CohortBucketing's docstring in
    # app/domain/models.py for why a plausible-looking default is exactly the
    # wrong move here.
    cohort_bucketing_boundaries: str | None = None

    # Google Places, used as a live lookup service only (docs/01_STACK_DECISIONS.md).
    google_places_api_key: str | None = None

    # Google OAuth. Auth is deliberately not scaffolded yet; these are declared
    # so the deployment contract is complete, not because anything reads them.
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None

    def require(self, field: str) -> str:
        """Return a setting's value, or raise if it is unset.

        Args:
            field: attribute name on this class, e.g. "database_url".

        Raises:
            RuntimeError: if the setting is unset or empty.
        """
        if not hasattr(self, field):
            raise AttributeError(f"No such setting: {field!r}")
        value = getattr(self, field)
        if not value:
            raise RuntimeError(
                f"Required setting {field.upper()} is not set. "
                f"Set it in the environment or in a .env file "
                f"(see .env.example for the documented keys)."
            )
        return str(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read from the environment once."""
    return Settings()
