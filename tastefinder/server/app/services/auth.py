"""
app/services/auth.py
---------------------
Ordinary identity: Google OAuth to a pseudonymous account (docs/05_AUTH_
DESIGN.md, Part 1).

Pure functions and a small interface, no database session -- same layer as
`privacy_gate.py` and `consent.py`. Orchestrating these across a session
(look up or create a `User`, write an `IdentityLink`, write an `AuthSession`)
is `persistence/auth_store.py`'s job, the way `founding_store.py` sits above
`community_founding.py`.

Two secrets, two different treatments, both explained in docs/05:

- The Google `sub` is a guessable-in-principle identifier from a known
  namespace, so it is HMAC'd with a server-held pepper (`hash_subject`) --
  an unkeyed hash of it would be reversible by anyone willing to enumerate.
- A session token is generated here, by us, with `secrets.token_urlsafe`.
  It is already high-entropy and never guessable, so it needs no pepper --
  a plain SHA-256 digest (`hash_token`) is enough to keep a database leak
  from handing out usable bearer tokens directly, the same property
  `hash_subject` buys for the identity link.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Protocol

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import verify_oauth2_token

# How long a server-issued session is valid for. An ordinary security
# default -- unlike min_cohort_threshold or the noise parameters, getting
# this wrong does not weaken a privacy guarantee, it only changes how often a
# user re-signs-in -- so it lives here as a constant rather than as another
# required-with-no-default setting, the way FOUNDING_MINIMUM_VENUES does in
# community_founding.py.
SESSION_TTL = timedelta(days=30)


class InvalidIdTokenError(Exception):
    """A Google ID token failed verification: bad signature, wrong audience,
    expired, or malformed. Deliberately does not echo the token or claims --
    same reasoning `FoundingError` gives for its own messages."""


def hash_subject(pepper: str, sub: str) -> str:
    """`HMAC-SHA256(pepper, sub)`, hex-encoded. See the module docstring."""
    return hmac.new(pepper.encode("utf-8"), sub.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_session_token() -> str:
    """A fresh, high-entropy bearer token. Returned to the client once."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 of a session token, hex-encoded. See the module docstring."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class IdTokenVerifier(Protocol):
    """Verifies a Google ID token and returns its `sub` claim.

    An interface, not a concrete call, for the same reason Google Places is
    specified as "a live lookup service only, behind an interface"
    (docs/01_STACK_DECISIONS.md): the real implementation is a network call
    to Google, and tests need a substitute that makes none.
    """

    def verify(self, id_token: str) -> str:
        """Return the verified `sub` claim.

        Raises:
            InvalidIdTokenError: the token's signature, audience, or
                expiry did not check out, or it carried no `sub`.
        """
        ...


class GoogleIdTokenVerifier:
    """Verifies a Google-issued ID token via `google-auth`.

    Checks the signature against Google's published keys (fetched over the
    network, hence a live call, not a stored secret) and that `aud` matches
    `client_id`. Nothing from the token beyond `sub` is read here -- email,
    name, and picture are present on the same claims but are exactly what
    docs/05_AUTH_DESIGN.md says must never be stored.
    """

    def __init__(self, client_id: str) -> None:
        self._client_id = client_id

    def verify(self, id_token: str) -> str:
        try:
            # google-auth ships py.typed but leaves this function itself
            # unannotated, hence the ignore -- not a stand-in for real types.
            claims = verify_oauth2_token(  # type: ignore[no-untyped-call]
                id_token, GoogleAuthRequest(), self._client_id
            )
        except (ValueError, GoogleAuthError) as exc:
            raise InvalidIdTokenError("Google ID token failed verification.") from exc
        sub = claims.get("sub")
        if not sub:
            raise InvalidIdTokenError("Google ID token carried no subject claim.")
        return str(sub)
