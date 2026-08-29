# 03 — API Contract

The HTTP surface between client and server. FastAPI generates the OpenAPI schema
from the implementation; the Dart client models are generated from that schema.
This document specifies what the surface should be — it is not itself generated.

## Principles

1. **The client never sees another user's data.** There is no endpoint that
   returns an individual's contributions, not even the caller's own history in
   aggregate-reconstructable form. See `INV-EXPOSE-1`.
2. **Aggregate reads go through the privacy gate.** No route may read a
   `CommunityAggregate` and serialise it directly. Every aggregate response is a
   `PublicAggregateView` produced by `PrivacyGate`.
3. **Suppression is indistinguishable from absence.** A slice below threshold and
   a slice with no data must return the same response. If they differ, the
   difference itself reveals that a small cohort exists — see `INV-EXPOSE-3`.
4. **Writes are fire-and-forget from the client's perspective.** Submitting a
   contribution returns a receipt, not the resulting aggregate. Returning the
   updated aggregate would let a client diff before/after and isolate its own
   contribution's effect — the differencing attack in miniature.

## Bootstrap phase

Only one endpoint exists after Phase 1.

```
GET /health → 200 {"status": "ok"}
```

Everything below is **specification for later phases**, recorded now so the
shape is agreed before implementation. Do not build these during bootstrap.

## Planned surface

### Communities

```
GET  /communities
     → 200 [{community_id, slug, status}]
     Public. Never includes cohort_size or membership lists.

GET  /communities/{slug}
     → 200 {community_id, slug, status, facets: [{facet_id, name, value_type,
            scale_min, scale_max}]}
     → 404 if not found.
     Note: a SEEDING community is visible but exposes no aggregates.
```

### Membership

```
POST /communities/{slug}/membership
     body: {}                       (identity comes from the session)
     → 201 {membership_id, tier}
     Tier is assigned server-side by community status: SEEDING → FOUNDER,
     LIVE → JOINER. The client does not choose its own tier.

DELETE /communities/{slug}/membership
     → 204
     Leaving does not retroactively remove folded contributions — they are no
     longer attributable and cannot be unfolded. This must be stated plainly in
     the consent copy before a user contributes, not discovered afterwards.
```

### Venue lookup

```
GET  /places/search?q={query}
     → 200 [{place_id, display_name, formatted_address}]
     Server-side proxy to VenueLookupService. The API key stays on the server.
     Results are pass-through and MUST NOT be persisted beyond place_id.
     See INV-CACHE-1.

GET  /places/{place_id}
     → 200 {place_id, display_name, formatted_address}
     Fetched live per request. Not served from a local cache of display fields.
```

### Contributions

```
POST /communities/{slug}/contributions
     body: {place_id, facet_scores: {facet_id: value}, free_text?: string}
     → 202 {contribution_id, accepted_at}

     202, not 201: the contribution is accepted for folding, not stored as a
     retrievable resource. There is deliberately no
     GET /contributions/{id} — that route must never exist (INV-EXPOSE-1).
```

### Aggregates

```
GET  /communities/{slug}/places/{place_id}/aggregate
     → 200 {community_id, place_id, facet_summaries, cohort_size_bucket}
     → 404 if suppressed OR absent — identical response for both (INV-EXPOSE-3).

GET  /communities/{slug}/aggregates?bbox=...
     → 200 [PublicAggregateView]
     Only slices above threshold are included. Suppressed slices are omitted
     silently — no placeholder entries, no "hidden" markers, no counts of how
     many were withheld.
```

### Consent and import (later phase — spec only)

```
POST /consent
     body: {scope: ConsentScope}
     → 201 {consent_id, scope, granted_at, expires_at?}

POST /consent/{consent_id}/revoke
     → 200 {consent_id, revoked_at}

POST /imports/google
     body: {consent_id}
     → 202 {job_id, state}
     Requires an active ConsentRecord with a GOOGLE_IMPORT_* scope (INV-CONSENT-1).

GET  /imports/google/{job_id}
     → 200 {job_id, state, completed_at?}
     Returns state only. Never returns the signed URL or any archive content.
```

## Error conventions

- `400` malformed request
- `401` no valid session
- `403` authenticated but not a member of the community
- `404` not found **or suppressed** — deliberately conflated
- `409` state conflict (e.g. duplicate membership)
- `422` validation failure (FastAPI default)
- `429` rate limited

Error bodies carry a stable `code` and a human-readable `message`. The message
must never name a specific user, contribution, or cohort size.

## Rate limiting

Aggregate read endpoints must be rate-limited before any public launch. Not for
capacity — an unthrottled aggregate endpoint is the most practical vector for a
differencing attack, since it lets an observer poll for changes. Treat it as a
privacy control, not an ops control.

It is also the first line of defence against Sybil-style abuse of the write path
(many accounts posting many contributions quickly) until the bot/Sybil-resistance
work in `docs/01_STACK_DECISIONS.md` is implemented — rate limit contribution
endpoints per-account and per-device from the start, not just aggregate reads.
