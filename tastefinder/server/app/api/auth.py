"""
app/api/auth.py
----------------
`POST /auth/google` -- the sign-in exchange from `docs/05_AUTH_DESIGN.md`,
Part 1.

The client already completed native Google Sign-In and holds an ID token;
this route verifies it, resolves it to a pseudonymous account (minting one on
a first sign-in), and issues a server session. Nothing from the Google
response reaches this route except the ID token the client sends and the
`sub` claim `IdTokenVerifier` extracts from it -- no email, name, or picture
is read, let alone stored.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_id_token_verifier, get_identity_pepper, get_session
from app.api.schemas import GoogleSignInIn, SessionOut
from app.persistence.auth_store import get_or_create_user, issue_session
from app.services.auth import IdTokenVerifier, InvalidIdTokenError, hash_subject

router = APIRouter(tags=["auth"])


@router.post("/auth/google", response_model=SessionOut, status_code=200)
def sign_in_with_google(
    payload: GoogleSignInIn,
    session: Session = Depends(get_session),
    verifier: IdTokenVerifier = Depends(get_id_token_verifier),
    pepper: str = Depends(get_identity_pepper),
) -> SessionOut:
    try:
        sub = verifier.verify(payload.id_token)
    except InvalidIdTokenError as error:
        raise HTTPException(status_code=401, detail="Sign-in failed.") from error

    now = datetime.now(UTC)
    subject_hash = hash_subject(pepper, sub)
    account = get_or_create_user(session, subject_hash, now)
    issued = issue_session(session, account.user_id, now)
    session.commit()

    return SessionOut(session_token=issued.token, expires_at=issued.expires_at)
