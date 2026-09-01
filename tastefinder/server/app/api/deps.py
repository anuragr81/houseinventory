"""
app/api/deps.py
----------------
FastAPI dependencies: a database session per request, the platform's facet
catalogue, and the cohort-size bucketing policy.

All three are built lazily, on first use, not at import time or app startup --
`/health` must keep working with no database and no catalogue configured
(`app/config.py`'s whole reason for making every setting optional). A route
that needs one asks for it as a dependency, and only then does an unset
`DATABASE_URL`, `FACET_CATALOGUE_PATH`, or `COHORT_BUCKETING_BOUNDARIES` raise.

Tests override all three via FastAPI's `dependency_overrides` rather than
setting these environment variables, so nothing here needs to run to collect
the test suite.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.domain.facet_catalogue import FacetCatalogue, load_catalogue
from app.domain.models import CohortBucketing
from app.persistence.session import build_engine, build_session_factory


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return build_session_factory(build_engine())


def get_session() -> Iterator[Session]:
    """One session per request, closed when the request ends.

    Read routes need no explicit transaction: there is nothing here to
    commit, and `persist_founding`'s all-or-nothing guarantee is a concern
    for whichever route writes, not these.
    """
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


@lru_cache(maxsize=1)
def get_catalogue() -> FacetCatalogue:
    """The platform's facet catalogue, loaded once per process."""
    path = get_settings().require("facet_catalogue_path")
    return load_catalogue(path)


@lru_cache(maxsize=1)
def get_bucketing() -> CohortBucketing:
    """The platform's cohort-size bucketing policy, built once per process.

    `CohortBucketing` deliberately has no default instance (see its
    docstring), so -- like the facet catalogue above -- the boundaries are
    required at the point of use rather than defaulted.
    """
    raw = get_settings().require("cohort_bucketing_boundaries")
    try:
        boundaries = tuple(int(part) for part in raw.split(","))
    except ValueError as exc:
        raise RuntimeError(
            f"COHORT_BUCKETING_BOUNDARIES must be a comma-separated list of "
            f"integers, e.g. '0,10,25,50,100'. Got: {raw!r}"
        ) from exc
    return CohortBucketing(boundaries=boundaries)
