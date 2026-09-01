# 05 — Authentication

Specification, not implementation. Nothing here is built yet.

`docs/01_STACK_DECISIONS.md` deferred this ("Sign-in will involve Google OAuth,
but session handling and account model are not settled"). Part 1 below settles
it.

> **Part 2 of this document has been removed.** It specified a
> joint-authorisation mechanism — a `POST /founding-authorisations` endpoint,
> HMAC tokens binding `(user_id, contribution_hash, slug, expires_at)`,
> client-side hash canonicalisation, and a slug-binding replay analysis — which
> existed **solely** to let five distinct users authorise one founding request.
>
> Founding no longer requires five users (see the rule history under "Founding
> a community" in `docs/03_API_CONTRACT.md`): the requirement was meant to buy
> bot resistance, proved five *accounts* rather than five *people*, and cost
> four other sign-ups before a community could exist at all. `POST /communities`
> is now an ordinary authenticated request from one founder, so none of that
> machinery is needed.
>
> The problem it solved is gone too. "One request, five authorisations" existed
> because five people submitting separately would have meant the server holding
> four identified contributions while waiting for a fifth — the structure
> `INV-RAW-2` forbids. With one founder there is nothing to wait for.
>
> If a joint act ever returns — a co-signed founding, a group endorsement — the
> design is in this file's history rather than lost. The two ideas worth
> recovering from it: the client should compute the contribution hash so the
> issuance endpoint never receives rating data, and slug-binding gives replay
> protection without a nonce table.

---

## Part 1 — Ordinary identity: Google OAuth to a pseudonymous account

### The tension

Google returns a stable `sub` claim identifying an account. `User` carries a
random `user_id` and `created_at`, and nothing else, deliberately. A returning
user needs *some* durable mapping from their Google identity back to their
`user_id`, or they cannot get into their own account twice.

`User`'s own docstring anticipated this: *"If authentication later needs a link
to an external identity, it goes in a separate table with its own
justification — not here."* This is that table and that justification.

### The identity link

A separate table, holding a mapping and nothing else:

```
identity_link
  subject_hash   CHAR(64)   PK   -- hex HMAC-SHA256, see below
  user_id        UUID       FK -> user.user_id
  created_at     DATETIME
```

**The Google `sub` is never stored in plaintext.** What is stored is
`HMAC-SHA256(server_pepper, sub)`. Lookup is unaffected — hash the incoming
`sub` and select the row — but a database leak yields opaque digests rather
than a list of Google account identifiers, and the pepper is not in the
database to leak alongside them.

HMAC rather than a bare hash because `sub` values are guessable-in-principle
identifiers from a known namespace; an unkeyed digest of one is reversible by
anyone willing to enumerate. The pepper is what makes the digest useless
without the server.

**The pepper comes from the environment** (`IDENTITY_PEPPER`), never the repo,
per `CLAUDE.md`'s no-secrets rule. Rotating it invalidates every mapping and
orphans every account, so it is a permanent secret, backed up as carefully as
the database.

**Nothing else from the OAuth response is stored.** Not email, not name, not
profile picture, not the raw ID token. They are used during the exchange and
discarded, the way `RawContribution.free_text` is used and discarded.

### Sessions

After the OAuth exchange, the server issues its own session credential — a
bearer token the Flutter client keeps in platform secure storage
(Keychain/Keystore), sent as `Authorization: Bearer`. Bearer rather than
cookies because the client is a mobile app, not a browser, and cookie
semantics buy nothing here.

Session tokens are the server's own, not Google's: the Google ID token is
verified once at sign-in and never used as an ongoing credential.

---

## What this adds to the persisted set

| Table | Holds | Why it is not a breach |
|---|---|---|
| `identity_link` | `subject_hash`, `user_id`, `created_at` | No plaintext external identifier, no rating data, never joined to aggregates |
| session storage | session token, `user_id`, expiry | Ordinary session state; carries no rating data |

Nothing else. Founding needs no auth-specific storage now that it is an
ordinary authenticated request.

---

## Invariants this adds

Written into `docs/04_PRIVACY_INVARIANTS.md` as `INV-AUTH-1`.

- **`INV-AUTH-1`** — The identity link stores no plaintext external identifier
  and is never joined to rating data.

`INV-AUTH-2` was drafted alongside Part 2 and removed with it: it required a
founding authorisation to carry a hash rather than a contribution, and there
are no founding authorisations any more.

---

## What this does not solve

- **Sybil resistance is still `OPEN-6`, and now matters more.** A valid session
  proves an account, not a person. With founding down to one user, there is no
  point anywhere in the platform where multiple distinct humans are
  structurally required — so `OPEN-6` and `OPEN-7` carry weight they did not
  when a founding needed five accounts. Device attestation, when it arrives,
  belongs at sign-in.
- **There is still no anonymous founding.** A founder must complete Google
  sign-in before their community exists — but that is now one person's sign-up
  rather than five, which was the point of the change.
- **Account recovery is unaddressed.** Lose access to the Google account and
  the `identity_link` row is unreachable; there is no second factor and no
  recovery path. Adding one means storing something else about a person, which
  is the trade `CLAUDE.md` reserves to the owner.
- **`IDENTITY_PEPPER` has no rotation story**, by construction — see above.
