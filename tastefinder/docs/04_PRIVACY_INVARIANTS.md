# 04 — Privacy Invariants

This is the load-bearing document. It converts the legal and privacy analysis in
Sections 7 and 8 of the design report from prose into **testable assertions**, so
that the analysis constrains the code rather than sitting next to it.

## Rules for this file

- Every invariant has an ID. Every invariant has at least one test whose name
  contains that ID.
- These tests do not get skipped, xfailed, or relaxed to make a build pass. A
  failing invariant test means the code is wrong.
- Adding an invariant is welcome. **Removing or weakening one is a decision for
  the project owner, not for an implementer or an agent.**
- Where an invariant says "MUST NOT exist", a test asserting absence is required
  — it is not enough that the thing merely hasn't been built yet.

---

## Group RAW — transient identified data

The report's central architectural claim: identified per-person data is
processed briefly at contribution time and never retained.

### `INV-RAW-1` — Raw contributions do not survive folding
After a `RawContribution` has been folded into a `CommunityAggregate`, it must no
longer be readable through any application code path.

*Test:* submit a contribution, fold it, then assert that every retrieval path
(repository lookup by ID, by user, by community, by place) returns nothing.

### `INV-RAW-2` — No user-indexed contribution history
There must be no query, index, ORM relationship, or table that returns the set of
contributions belonging to a given `user_id`.

*Test:* introspect the mapped tables and assert no persisted table exposes both
`user_id` and rating/facet data on the same row after folding. Assert no
repository method takes a `user_id` and returns contributions.

### `INV-RAW-3` — Free text is not retained
`free_text` is the highest-identifiability field on a contribution (writing style
and specific detail are effectively a fingerprint). It must be consumed during
normalisation into facet values and never persisted to the aggregate layer.

*Test:* assert no persisted model has a free-text field; assert
`PublicAggregateView` contains no string field capable of holding review prose.

### `INV-RAW-4` — Logs do not leak contributions
Contribution payloads must never be written to application logs, error trackers,
or request-tracing output — including inside exception handlers.

*Test:* trigger a handled and an unhandled failure during contribution
processing; capture log output; assert it contains neither `user_id` nor facet
values nor free text.

---

## Group EXPOSE — what may leave the system

### `INV-EXPOSE-1` — No individual read path
No API route may return data attributable to an identified individual — including
to that individual themselves. `GET /contributions/{id}` and any equivalent must
not exist.

*Test:* enumerate the generated OpenAPI routes and assert none matches an
individual-contribution retrieval pattern.

### `INV-EXPOSE-2` — Exact cohort size is never published
Responses expose `cohort_size_bucket`, never `cohort_size`.

*Test:* serialise a `PublicAggregateView` and assert the exact integer does not
appear in the payload under any key.

### `INV-EXPOSE-3` — Suppressed is indistinguishable from absent
A below-threshold slice and a non-existent slice must produce byte-identical
responses, including status code, body, and headers. Response timing should not
be trivially distinguishable either.

*Test:* request an aggregate for a place with a sub-threshold cohort and for a
place with no data at all; assert responses are equal.

### `INV-EXPOSE-4` — Threshold is enforced at every read, per slice
Suppression is applied on every query, for every slice, not once at community
go-live. A `LIVE` community does not imply every geographic or per-venue cut of
it is safe to expose.

*Test:* property-based — for arbitrary aggregates and thresholds, assert nothing
with `cohort_size < min_cohort_threshold` is ever returned by any read path.

### `INV-EXPOSE-5` — No unsuppressed serialisation path
`CommunityAggregate` must not be directly serialisable to an API response. Only
`PublicAggregateView` is.

*Test:* assert no route's declared response model is `CommunityAggregate`; assert
`CommunityAggregate` has no response-serialisation configuration.

---

## Group CACHE — Google Maps Platform terms

Derived from report §8.4. These are contractual obligations under the Google Maps
Platform Terms of Service, in addition to being good minimisation practice.

### `INV-CACHE-1` — Only `place_id` is stored indefinitely
Display fields obtained from Places (name, formatted address, rating, photos,
opening hours, review content) must not be persisted. `place_id` may be stored
indefinitely; latitude/longitude may be cached for a bounded period only.

*Test:* introspect `PlaceRef` and assert it has no display-field columns; assert
coordinate cache entries older than the configured retention are purged.

### `INV-CACHE-2` — Coordinate cache expiry is enforced
Cached coordinates past their retention window must be treated as absent and
refetched, not served stale.

*Test:* set `coords_cached_at` beyond the window; assert `needs_refresh()` is
true and that the read path refetches rather than returning the cached value.

> **Check the current terms before relying on the configured window.** The
> retention period and the set of cacheable fields are set by Google's
> then-current Places policies, which change. The report cites them as at
> August 2026. Treat the configured value as something to re-verify, not as a
> constant.

### `INV-CACHE-3` — No derived venue catalogue
The platform must not accumulate a queryable venue directory. There must be no
route or query that lists or searches `PlaceRef` rows by anything other than an
exact `place_id`.

*Test:* assert no repository method returns multiple `PlaceRef` rows by name,
text, or geographic search.

---

## Group CONSENT — lawful basis and transparency

### `INV-CONSENT-1` — No import without active consent
A Google import job may only be initiated where an active, unrevoked, unexpired
`ConsentRecord` with a `GOOGLE_IMPORT_*` scope exists for that user.

*Test:* attempt initiation with (a) no consent, (b) revoked consent, (c) expired
consent, (d) a `DIRECT_CURATION`-scoped consent. All four must be refused.

### `INV-CONSENT-2` — Consent records are append-only
Revocation writes `revoked_at`. No code path updates `scope` or `granted_at`, or
deletes a consent row.

*Test:* attempt mutation and deletion through the repository; assert both fail.

### `INV-CONSENT-3` — Signed URLs are never persisted
Google archive signed URLs are held in memory for the download only.

*Test:* assert `GoogleImportJob` has no signed-URL column; assert the URL never
appears in logs.

### `INV-CONSENT-4` — Scope separation
Consent to direct curation does not authorise Google import, and one-time import
consent does not authorise repeat imports.

*Test:* assert each scope authorises only its own operation.

---

## Group MINOR — age

### `INV-MINOR-1` — Import is unavailable to under-18 accounts
Google's Data Portability API does not support access by accounts of users under
18 (report §8.5). The import path must fail closed if age eligibility is not
positively established.

*Test:* assert that absent or indeterminate age eligibility refuses the import,
rather than defaulting to allow.

---

## Open — must be resolved before production

These are **not yet invariants** because the underlying decisions are open. They
are recorded here so they are not forgotten, and so nobody mistakes silence for
"handled".

### `OPEN-1` — Minimum cohort threshold value
No safe default exists. Must be set per community, above the suppression floor,
by a decision that is documented. Until set, `min_cohort_threshold` has no
default and the system should refuse to publish.

### `OPEN-2` — Differencing defence
Threshold suppression alone does not defeat differencing across successive
releases. Batched or scheduled aggregate updates, and/or calibrated noise, are
required. The `PrivacyGate.apply_noise` interface exists; the mechanism does not.

### `OPEN-3` — Privacy mechanism and parameters
Threshold suppression vs. differential privacy is unresolved, and epsilon must
not be guessed. This choice also determines whether `FacetStat` remains a
mean/variance/n triple.

### `OPEN-4` — Re-identification testing
A motivated-intruder test against the public Google review corpus has not been
performed. Until it has, the threshold values are unvalidated assumptions.

### `OPEN-5` — DPIA and legal review
No DPIA exists. Nothing in this file substitutes for review by a UK
data-protection solicitor of the consent flows, privacy notices, and retention
model.

### `OPEN-6` — Bot / Sybil resistance
Not implemented. Direction chosen — device attestation (Play Integrity / App
Attest), a founder/joiner-based vouching chain, contribution rate-limiting, and
tenure-weighting — but none built yet. See the full reasoning, including why
phone-number verification was considered and rejected, in
`docs/01_STACK_DECISIONS.md`.

The specific risk this needs to defend against is a Sybil attack on a single
aggregate (enough fake accounts in one community to manufacture a favourable
published verdict for a venue), not generic bot signups — and it interacts
directly with `OPEN-1`: whatever `min_cohort_threshold` is eventually set to is
also the number of accounts an attacker needs, so the two decisions should be
made with each other in view, not independently.

---

## For the agent

If you are implementing here and find yourself wanting to:

- add a field "just for debugging" that holds a user ID next to rating data,
- keep raw contributions "temporarily" to make aggregation easier to test,
- return the updated aggregate from the contribution endpoint for convenience,
- cache place display names to reduce API cost,
- log a full request body to diagnose a failure,
- add a phone number, email, or other strong identifier to `User` to solve a
  bot-resistance or verification problem,

…then stop. Each of those is a direct breach of an invariant above, and each is
an entirely reasonable-looking engineering instinct. That is precisely why they
are written down. Raise the problem instead; there is usually another way, and
where there isn't, the trade-off is the owner's to make.
