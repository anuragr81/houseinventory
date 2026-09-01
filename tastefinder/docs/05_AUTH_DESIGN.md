# 05 — Authentication and Joint Authorisation

Specification, not implementation. Nothing here is built yet.

`docs/01_STACK_DECISIONS.md` deferred this ("Sign-in will involve Google OAuth,
but session handling and account model are not settled"), and
`docs/03_API_CONTRACT.md` flagged the unusual half of it: `POST /communities`
needs **five distinct users to authorise one request submitted by a sixth
party — one of themselves**. That is not how session auth normally works, and
discovering it late would be expensive.

These are two separable problems and this document keeps them separate.

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

## Part 2 — Joint authorisation: five founders, one request

### The flow

1. The founder picks a `slug` and shares it with the four others, out of band
   or through the app.
2. **Each of the five, in their own authenticated session, calls
   `POST /founding-authorisations`.** Their client computes a canonical hash of
   the contribution that person is authorising and sends **only the hash**,
   with the slug. The server returns a signed token.
3. Each of the four hands their token **and their actual contribution** to the
   founder's client.
4. The founder submits `POST /communities` carrying all five contributions and
   all five tokens.
5. The server verifies each token, checks the five `user_id`s are distinct,
   and checks each token's hash matches the contribution actually submitted
   alongside it.

### The client computes the hash, not the server

The issuance endpoint receives a digest, never facet scores or free text. That
is deliberate: an endpoint that never receives rating data cannot log it,
leak it, or be tempted to keep it, and the contribution reaches the server
exactly once — in the founding request itself.

The server does not need to trust *what* was hashed. The token asserts only
"this user authorised whatever hashes to X". If a founder substitutes
different ratings, the recomputed hash will not match X and the founding is
refused. The friend's own client computed X from what the friend actually
approved.

**The hash is over a canonical serialisation** — fields in a fixed order,
sorted facet keys, no insignificant whitespace — specified precisely at
implementation time and shared by client and server. An incidental
re-serialisation must not break the match.

### Token contents and signing

The token binds:

```
user_id            who authorised
contribution_hash  what they authorised
slug               which founding it is for
expires_at         when it stops being usable
```

Signed with HMAC-SHA256 using a server-held key (`FOUNDING_TOKEN_KEY`, from the
environment). **Not a JWT.** A JWT carries its own algorithm field, and
algorithm-confusion attacks against that field are a well-worn class of
vulnerability; there is nothing to negotiate here, so the format pins one
algorithm and offers no field to lie about it.

### Replay protection falls out of the design

There is deliberately **no consumed-nonce table**, because slug-binding already
does the work:

- The slug is signed into every token, so five intercepted tokens can only ever
  attempt to found *that* slug. Once it exists, any replay hits the `409` the
  unique constraint already produces.
- A single friend's token cannot be replayed to fake two founders: `user_id` is
  signed, and the server rejects a batch whose five tokens are not five
  distinct users.
- A failed founding (the bar was not met) leaves the tokens usable, which is
  correct — the group should be able to fix the batch and retry.

Expiry remains, to bound how long a leaked token is worth anything. **Proposed:
24 hours**, on the grounds that coordinating four other people is not
instantaneous, and that the value of a replayed token is already small. This is
a tunable parameter, not a derived one — shorten it if the threat model
changes.

If founding ever gains an effect that is not idempotent per slug, this
reasoning stops holding and a nonce table becomes necessary. That condition is
worth re-checking rather than assuming.

### Slugs are not reserved during the window

Two groups can authorise against the same slug concurrently; the second to
submit gets a `409`. Reserving slugs at authorisation time would mean holding
state per attempt and would let anyone squat a name for free. Losing a race is
recoverable — reauthorise against a different slug — and this keeps the
window stateless.

---

## What this adds to the persisted set

| Table | Holds | Why it is not a breach |
|---|---|---|
| `identity_link` | `subject_hash`, `user_id`, `created_at` | No plaintext external identifier, no rating data, never joined to aggregates |
| session storage | session token, `user_id`, expiry | Ordinary session state; carries no rating data |

Founding tokens are **not** persisted. They are signed, not stored — the
signature is what makes them verifiable without a server-side record.

---

## Invariants this adds

Written into `docs/04_PRIVACY_INVARIANTS.md` as `INV-AUTH-1` and `INV-AUTH-2`.

- **`INV-AUTH-1`** — The identity link stores no plaintext external identifier
  and is never joined to rating data.
- **`INV-AUTH-2`** — A founding authorisation carries a hash of a contribution,
  never the contribution. This is what preserves the property that motivated
  one-request-five-authorisations in the first place: the server never holds
  four people's identified contributions while waiting for a fifth.

---

## What this does not solve

- **Sybil resistance is still `OPEN-6`.** Five valid tokens prove five distinct
  *accounts*, not five distinct *people*. One person with five Google accounts
  satisfies every check in this document. Device attestation, when it arrives,
  belongs at token issuance — which is the natural place for it, and a reason
  to prefer server-issued tokens over client keypairs for now.
- **There is no anonymous founding.** All five must install the app and
  complete Google sign-in *before their community exists*. That is real
  friction on the critical path to any community existing at all, and it is a
  product consequence of this design rather than an accident of it.
- **Account recovery is unaddressed.** Lose access to the Google account and
  the `identity_link` row is unreachable; there is no second factor and no
  recovery path. Adding one means storing something else about a person, which
  is the trade `CLAUDE.md` reserves to the owner.
- **`IDENTITY_PEPPER` has no rotation story**, by construction — see above.
