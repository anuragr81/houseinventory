"""
app/persistence/auth_store.py
------------------------------
Writing the effects of a sign-in, across repositories, in one unit of work.

Same shape as `founding_store.py`: this is orchestration over a `Session`,
not a decision -- `services/auth.py` holds the pure pieces (hashing, token
generation, ID-token verification), and this module is what a route calls to
turn "a verified Google `sub`" into "a signed-in user with a bearer token."
It deliberately does not commit; the caller's transaction decides whether the
writes survive, same as `persist_founding`.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.models import AuthSession, IdentityLink, User
from app.persistence.repositories import IdentityLinkRepository, SessionRepository, UserRepository
from app.services.auth import SESSION_TTL, generate_session_token, hash_token


@dataclass(frozen=True)
class SignInResult:
    """Which account a sign-in resolved to, and whether it was just minted.

    A route may want to tell a first-time and a returning sign-in apart (a
    201 vs. 200, say); `identity_link` is not queryable from outside this
    call to recover that after the fact, so it is returned here instead.
    """

    user_id: UUID
    is_new_account: bool


@dataclass(frozen=True)
class IssuedSession:
    """A freshly minted session, as a route needs to render it: the raw
    bearer token (once) and when it expires. Not a domain model -- nothing
    persists this shape; `AuthSession` is what gets stored."""

    token: str
    expires_at: datetime


def get_or_create_user(session: Session, subject_hash: str, now: datetime) -> SignInResult:
    """Find the account this Google identity already maps to, or mint one.

    Founding refuses to mint an account as a side effect of someone else's
    request (`UnknownFounderError` in `founding_store.py`) -- this is the one
    place that is allowed to, because minting an account *is* the request.
    Sign-in is the identity decision `founding_store.py`'s docstring defers
    to.
    """
    link_repo = IdentityLinkRepository(session)
    existing = link_repo.get_user_id(subject_hash)
    if existing is not None:
        return SignInResult(user_id=existing, is_new_account=False)

    user = User(created_at=now)
    UserRepository(session).add(user)
    # The identity_link row's FK needs the user row to exist first.
    session.flush()
    link_repo.add(IdentityLink(subject_hash=subject_hash, user_id=user.user_id, created_at=now))
    return SignInResult(user_id=user.user_id, is_new_account=True)


def issue_session(session: Session, user_id: UUID, now: datetime) -> IssuedSession:
    """Mint a bearer token, store only its hash, return the raw token once.

    The raw token is never persisted (`services/auth.py`'s module docstring)
    and never logged -- the caller's only job is to hand it to the client and
    then let it go out of scope.
    """
    raw_token = generate_session_token()
    expires_at = now + SESSION_TTL
    SessionRepository(session).add(
        AuthSession(
            token_hash=hash_token(raw_token),
            user_id=user_id,
            created_at=now,
            expires_at=expires_at,
        )
    )
    return IssuedSession(token=raw_token, expires_at=expires_at)
