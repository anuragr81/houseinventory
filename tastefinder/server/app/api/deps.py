"""
app/api/deps.py
----------------
FastAPI dependencies: a database session per request, the platform's facet
catalogue, the cohort-size bucketing policy, Google ID-token verification,
and the signed-in user a bearer token resolves to.

All of these are built lazily, on first use, not at import time or app
startup -- `/health` must keep working with no database and no catalogue
configured (`app/config.py`'s whole reason for making every setting
optional). A route that needs one asks for it as a dependency, and only then
does an unset `DATABASE_URL`, `FACET_CATALOGUE_PATH`,
`COHORT_BUCKETING_BOUNDARIES`, `GOOGLE_OAUTH_CLIENT_ID`, or
`IDENTITY_PEPPER` raise.

Tests override these via FastAPI's `dependency_overrides` rather than
setting the environment variables, so nothing here needs to run to collect
the test suite.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.domain.facet_catalogue import FacetCatalogue, load_catalogue
from app.domain.models import CohortBucketing
from app.persistence.repositories import SessionRepository
from app.persistence.session import build_engine, build_session_factory
from app.services.auth import GoogleIdTokenVerifier, IdTokenVerifier, hash_token


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


@lru_cache(maxsize=1)
def get_identity_pepper() -> str:
    """The HMAC pepper `services/auth.py` keys `subject_hash` with.

    Required, no default -- see the field's docstring in `app/config.py` and
    `docs/05_AUTH_DESIGN.md`.
    """
    return get_settings().require("identity_pepper")


@lru_cache(maxsize=1)
def get_id_token_verifier() -> IdTokenVerifier:
    """The real, network-backed Google ID-token verifier, built once.

    Tests override this with a fake that makes no network call -- see
    `IdTokenVerifier`'s docstring for why it is an interface at all.
    """
    client_id = get_settings().require("google_oauth_client_id")
    return GoogleIdTokenVerifier(client_id)


def get_current_user_id(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> UUID:
    """The signed-in user, from `Authorization: Bearer <token>`.

    401, not 403, for every way this can fail -- missing header, wrong
    scheme, unknown token, expired token -- per `docs/03_API_CONTRACT.md`'s
    error conventions ("401 no valid session"). The failures are
    deliberately not told apart in the response: which one occurred is not
    something a caller who does not already hold a valid session needs.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not signed in.")
    token = authorization.removeprefix("Bearer ").strip()
    user_id = SessionRepository(session).user_id_for_token(
        hash_token(token), now=datetime.now(UTC)
    )
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user_id
