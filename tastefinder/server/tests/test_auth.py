"""
tests/test_auth.py
-------------------
`app/services/auth.py` (pure functions and the verifier interface) and
`app/persistence/auth_store.py` (sign-in orchestration).

`GoogleIdTokenVerifier` itself is not exercised here: it is a thin wrapper
around a network call to Google, and testing it would mean either a live
call or mocking `google-auth` internals, which proves little about this
codebase. What is tested is everything downstream of "some verifier returned
a `sub`" -- the interface boundary is exactly where a fake belongs.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.auth_store import get_or_create_user, issue_session
from app.persistence.repositories import IdentityLinkRepository, SessionRepository
from app.persistence.session import build_engine, build_session_factory, transaction
from app.persistence.tables import Base
from app.services.auth import SESSION_TTL, generate_session_token, hash_subject, hash_token

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
PEPPER = "test-pepper-do-not-use-in-production"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


# ── hash_subject ─────────────────────────────────────────────────────────────


def test_hash_subject_is_deterministic() -> None:
    assert hash_subject(PEPPER, "google-sub-1") == hash_subject(PEPPER, "google-sub-1")


def test_hash_subject_differs_by_sub() -> None:
    assert hash_subject(PEPPER, "sub-a") != hash_subject(PEPPER, "sub-b")


def test_hash_subject_differs_by_pepper() -> None:
    """The pepper is what makes the digest useless without the server."""
    assert hash_subject(PEPPER, "sub-a") != hash_subject("a-different-pepper", "sub-a")


def test_hash_subject_output_is_not_the_input() -> None:
    """INV-AUTH-1: the stored value must differ from the raw sub."""
    sub = "108234982734982734"
    assert hash_subject(PEPPER, sub) != sub


# ── session tokens ────────────────────────────────────────────────────────────


def test_generate_session_token_is_high_entropy_and_unique() -> None:
    tokens = {generate_session_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(token) >= 32 for token in tokens)


def test_hash_token_is_deterministic_and_not_the_input() -> None:
    token = generate_session_token()
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token


def test_hash_token_differs_by_token() -> None:
    assert hash_token(generate_session_token()) != hash_token(generate_session_token())


# ── auth_store.get_or_create_user ────────────────────────────────────────────


def test_a_new_subject_hash_mints_a_user_and_an_identity_link(
    factory: sessionmaker[Session],
) -> None:
    subject_hash = hash_subject(PEPPER, "new-user-sub")

    with transaction(factory) as session:
        result = get_or_create_user(session, subject_hash, NOW)

    assert result.is_new_account is True
    with transaction(factory) as session:
        assert IdentityLinkRepository(session).get_user_id(subject_hash) == result.user_id


def test_a_known_subject_hash_returns_the_same_user_without_minting_another(
    factory: sessionmaker[Session],
) -> None:
    subject_hash = hash_subject(PEPPER, "returning-user-sub")

    with transaction(factory) as session:
        first = get_or_create_user(session, subject_hash, NOW)
    with transaction(factory) as session:
        second = get_or_create_user(session, subject_hash, NOW + timedelta(days=1))

    assert second.user_id == first.user_id
    assert second.is_new_account is False


def test_different_subjects_get_different_users(factory: sessionmaker[Session]) -> None:
    with transaction(factory) as session:
        a = get_or_create_user(session, hash_subject(PEPPER, "sub-a"), NOW)
    with transaction(factory) as session:
        b = get_or_create_user(session, hash_subject(PEPPER, "sub-b"), NOW)

    assert a.user_id != b.user_id


# ── auth_store.issue_session ─────────────────────────────────────────────────


def test_issue_session_returns_a_token_and_an_expiry(factory: sessionmaker[Session]) -> None:
    with transaction(factory) as session:
        account = get_or_create_user(session, hash_subject(PEPPER, "sub"), NOW)
    with transaction(factory) as session:
        issued = issue_session(session, account.user_id, NOW)

    assert issued.expires_at == NOW + SESSION_TTL
    assert len(issued.token) >= 32


def test_issue_session_persists_only_the_token_hash(factory: sessionmaker[Session]) -> None:
    """A database read never yields the raw bearer token back."""
    with transaction(factory) as session:
        account = get_or_create_user(session, hash_subject(PEPPER, "sub"), NOW)
    with transaction(factory) as session:
        issued = issue_session(session, account.user_id, NOW)

    with transaction(factory) as session:
        resolved = SessionRepository(session).user_id_for_token(hash_token(issued.token), NOW)
        assert resolved == account.user_id
        # The raw token itself is not a valid lookup key -- only its hash is.
        assert SessionRepository(session).user_id_for_token(issued.token, NOW) is None


def test_an_expired_session_resolves_to_no_one(factory: sessionmaker[Session]) -> None:
    with transaction(factory) as session:
        account = get_or_create_user(session, hash_subject(PEPPER, "sub"), NOW)
    with transaction(factory) as session:
        issued = issue_session(session, account.user_id, NOW)

    with transaction(factory) as session:
        far_future = NOW + SESSION_TTL + timedelta(seconds=1)
        assert (
            SessionRepository(session).user_id_for_token(hash_token(issued.token), far_future)
            is None
        )


def test_an_unknown_token_resolves_to_no_one(factory: sessionmaker[Session]) -> None:
    with transaction(factory) as session:
        assert SessionRepository(session).user_id_for_token(hash_token("never-issued"), NOW) is None
