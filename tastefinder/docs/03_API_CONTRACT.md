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

Marked **[implemented]** below are wired up as real FastAPI routes; everything
else is still specification only, per the bootstrap phasing.

### Communities

```
POST /communities
     body: {slug, min_cohort_threshold, facet_keys: [string],
            contributions: [{place_id, facet_scores, free_text?}, ...]}
     → 201 {community_id, slug, status}
     → 401 if not signed in.
     → 409 if the slug is taken.
     → 422 if the batch does not meet the bar below.

     An ordinary authenticated request: the founder is the session's user.
     facet_keys selects from the platform's facet catalogue; a founder cannot
     author a facet name (INV-SCHEMA-1). facet_scores are keyed by the same
     catalogue keys, not by facet_id -- facet ids do not exist until founding
     creates them.

     Atomic: see "Founding a community".

GET  /facets  [implemented]
     → 200 [{key, name, value_type, scale_min, scale_max}]
     The platform's facet catalogue. A client needs this before it can build a
     founding request. Source is FACET_CATALOGUE_PATH (app/config.py) -- a
     JSON file, no default content shipped (see the module docstring on
     app/domain/facet_catalogue.py for why).

GET  /communities  [implemented]
     → 200 [{community_id, slug, status}]
     Public. Never includes cohort_size or membership lists.

GET  /communities/{slug}  [implemented]
     → 200 {community_id, slug, status, facets: [{facet_id, name, value_type,
            scale_min, scale_max}]}
     → 404 if not found.
     Note: a SEEDING community is visible but exposes no aggregates.
```

Neither read route goes through `PrivacyGate`: nothing here is a
`CommunityAggregate`, a cohort size, or contribution data, so there is nothing
for that gate to suppress. It exists for the aggregate routes below, which are
still specification only.

### Founding a community

Creating a community is deliberately not a lightweight metadata call. A founder
is defining the taste the community will aggregate around, so founding requires
demonstrating that taste rather than asserting it. There is **no human approval
step** — the filter is effort, not permission.

**The bar.** One request must carry ratings for at least **five distinct
venues**, contributed by the founder. Distinct *venues*, not contributions:
rating the same place five times is not knowing five places. If the bar is not
met the request fails and no community is created — there is no partially
founded state.

> **Rule history, kept because the reasoning matters.** Founding originally
> required **five distinct users**, each creditable with a distinct venue, all
> authorising a single atomic request. That rule was dropped, and the reason it
> was wrong is worth keeping.
>
> It was meant to buy bot resistance, and it did not. Five authorisations prove
> five *accounts*, not five *people* — one person with five Google accounts
> satisfied every check in it. Meanwhile it cost a great deal: four other
> people each had to install the app and complete sign-in *before the community
> existed at all*, with nothing yet to show them and no way to preview what
> they were joining. It was a large, unavoidable barrier on the critical path
> to any community existing, paying for a property it never actually delivered.
>
> The effort filter survives the change. One person rating five venues
> demonstrates a coherent taste at least as well as five people each rating
> one — arguably better, since five people who each know one place is weaker
> evidence of a shared taste than one person who knows five.
>
> Dropping it also removed a whole subsystem: the joint-authorisation
> mechanism in `docs/05_AUTH_DESIGN.md` (token issuance, HMAC format,
> client-side hash canonicalisation, slug-bound replay analysis) existed
> **solely** to let five people authorise one request. Founding is now an
> ordinary authenticated `POST`.

**What this leaves unguarded, stated plainly.** There is now no point anywhere
in the platform where multiple distinct humans are structurally required. One
actor can found a community alone and, because `cohort_size` counts
contributions rather than contributors, raise a venue past its threshold by
contributing repeatedly. That was already true (`OPEN-7`), but the five-founder
rule was an incidental speed bump in front of it. Removing the bump does not
create the hole; it makes `OPEN-6` and `OPEN-7` load-bearing rather than
theoretical.

**What is persisted, and what is not.** The founding contributions go through
the ordinary path — `RawContribution`, folded by `StreamingAggregator`, purged.
There is no founder-specific ingestion route, because a second path for
identified data is exactly what the invariants exist to prevent.

**Facets are selected, not written.** A founding request carries `facet_keys`
naming entries in the platform's catalogue (`GET /facets`); the community's
facets are created from those definitions in the same transaction, and the
contributions in the same request score them by the same keys.

This is a privacy control, not tidiness. A founder-authored facet name would be
the first thing in this system that is user-written, persisted indefinitely,
and published — everything else is either transient or numeric. That
combination is what lets a name carry a third party's personal data, published
with community ratings attached, about someone who never consented and has no
erasure path. Selecting from a catalogue removes the possibility instead of
promising to moderate it. See `INV-SCHEMA-1`.

It does not close the whole hole: `slug` is still founder-supplied, persisted,
and published. That surface is far smaller and structurally constrained, and it
is why an operational takedown channel is still needed — recorded as `OPEN-8`.

**Tier is set by how a member arrived, not by the community's status.** The
founder receives `FOUNDER`. Everyone who joins afterwards receives `JOINER`,
whether the community is `SEEDING` or `LIVE`.

This is a change from an earlier draft, which assigned tier by status
(`SEEDING → FOUNDER`). That rule predates the decision that founding is a
single atomic act by a group of five: under it, members six through twenty of a
still-seeding community would also have been founders, and "the founding group"
would have had no durable meaning. It also matters downstream — the vouching
chain sketched in `docs/01_STACK_DECISIONS.md` for `OPEN-6` hangs off the
founder/joiner distinction, and needs it to identify a specific small group
rather than everyone who happened to arrive early.

`SEEDING` and `LIVE` consequently describe scale only: whether the community has
reached the point where anything can be published, which is what
`Community.can_go_live()` already computes. They no longer influence tier.

**A founded community usually publishes nothing at first, and that is correct.**
Community visibility and aggregate publishability are separate gates. Meeting
the founding bar makes the community appear in `GET /communities`; it does not
make any venue's rating publishable. Each venue is suppressed independently
until that venue clears `min_cohort_threshold` (`INV-EXPOSE-4`), and five
founders spread across five venues leaves every one of them at a cohort of one.
A new community will typically be visible, joinable, and empty of ratings until
enough joiners overlap on the same places.

Do not "fix" this by exempting founders from suppression. At a cohort of one or
two, successive reads of an aggregate let an observer solve for an individual's
exact score from the change in the mean — the differencing attack in `OPEN-2`,
which needs no knowledge of who the contributors are. Pseudonymity does not
defend against it; only the threshold does.

**Open parameters.** The founding minimum is currently five distinct venues. It
is a starting value, not a derived one, and it is **not** the same number as
`min_cohort_threshold` (`OPEN-1`) — one governs what it takes to start a
community, the other what it takes to publish a venue's rating. Both are the
owner's to set.

**The bar is an effort filter and nothing more.** It says the founder has
opinions about five places. It says nothing about whether they are a real
person, a distinct person, or acting alone — that is `OPEN-6`, deferred
platform-wide, and founding no longer pretends to contribute to it. Do not
describe this bar as an anti-Sybil control.

### Membership

```
POST /communities/{slug}/membership
     body: {}                       (identity comes from the session)
     → 201 {membership_id, tier}
     Always JOINER. The client does not choose its own tier.

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
