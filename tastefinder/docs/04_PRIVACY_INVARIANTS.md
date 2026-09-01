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

## Group SCHEMA — what users may write that survives a request

Everything else in this document governs data that is either transient
(`RawContribution`) or numeric (`FacetStat`). This group exists because
founding introduced the first candidate for something else: text a user writes
that is persisted indefinitely and published.

### `INV-SCHEMA-1` — Facet names come from the platform, never from a request

A community selects facets from a catalogue the platform owns. No API input
may set a facet's `name`. A user-authored facet name would be persisted
indefinitely and published by `GET /communities/{slug}`, which is exactly the
combination that lets it carry a third party's personal data ("how good is
<a named person>'s bedside manner") — published with community ratings
attached, about someone who never consented, with no erasure path and no
moderation. `CLAUDE.md` already says members rate on a schema *the platform
owns*; this makes that structural rather than aspirational.

*Test:* assert `found_community` rejects a facet key outside the catalogue;
assert every persisted facet name is one the catalogue defines.

### `INV-SCHEMA-2` — Only scoreable facet types may be offered

`FacetStat` is a mean/variance/n triple over floats. A `TEXT` facet cannot be
scored by it, and the only way to make one work would persist per-contribution
prose — which `INV-RAW-3` forbids. Offering a `TEXT` facet is therefore a
promise the system cannot keep, and it must be refused where the catalogue is
built rather than where a contribution arrives.

*Test:* assert constructing a catalogue entry with `value_type = TEXT` raises.

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

### `OPEN-7` — `cohort_size` counts contributions, not contributors

Surfaced while implementing the aggregator in Phase 3, and recorded here rather
than decided.

`StreamingAggregator.fold` increments `cohort_size` once per contribution. It
does **not** de-duplicate by contributor, because it cannot: telling a repeat
contributor from a new one requires a per-aggregate record of which users have
already contributed, which is exactly the user-indexed structure `INV-RAW-2`
forbids. So `cohort_size` is an upper bound on the number of distinct people
behind a slice, not the number itself.

Why this matters rather than being a naming quibble: `min_cohort_threshold` is
a *privacy* parameter, and it is being compared against a number that a single
person contributing repeatedly can inflate on their own. Ten contributions from
one enthusiastic member currently reads as a cohort of ten and publishes. That
weakens the suppression guarantee `INV-EXPOSE-4` rests on, and it overlaps with
`OPEN-6`: an attacker needs fewer accounts than the threshold suggests.

The options, none of them chosen here:

- Rate-limit contributions per account and per venue, so repeat contributions
  are bounded without being counted (`docs/03_API_CONTRACT.md` already asks for
  this on the write path, for Sybil reasons).
- Hold a per-aggregate cardinality sketch (e.g. HyperLogLog) over salted user
  identifiers, which estimates distinct contributors without storing a
  membership list. This persists a derivative of `user_id` next to rating data
  and would need to be weighed against `INV-RAW-2` explicitly, not slipped in.
- Accept the upper bound and set `OPEN-1`'s threshold high enough to absorb it.

**This is the project owner's decision.** Whichever way it goes, it should be
made alongside `OPEN-1` and `OPEN-6`, since all three set the same number from
different directions.


### `OPEN-8` — No moderation or takedown channel

`INV-SCHEMA-1` removes user-authored facet *names*, but `Community.slug` is
still supplied by a founder, persisted indefinitely, and published by
`GET /communities`. A slug is structurally constrained and much smaller a
surface than a free-text facet name, but "someone-is-a-fraud" is a valid slug,
and nothing in this system can currently remove or rename one.

This is operational rather than implementational — deciding whether a
particular slug is defamatory needs human review, a reporting route, and a
takedown policy, none of which are code. It is recorded here for the same
reason `OPEN-6` is: the direction is known, the mechanism is deferred, and it
must not be mistaken for handled.

Two things it needs from the implementation side, both cheap now and expensive
later:

- **A rename/removal path** for slugs and facets. Written-once rows cannot be
  taken down without a manual intervention against production.
- **A decision about authorship.** Nothing records which founder supplied a
  slug, deliberately. That is good for privacy and bad for accountability: my
  non-expert reading is that an operator's defence under the Defamation Act
  2013 turns on either identifying the poster or responding properly to a
  notice, and we currently have neither. Which of those to build is the
  owner's call, and it wants the solicitor's review `OPEN-5` already asks for.

Unlike `OPEN-6`, whose failure mode is contained within the platform's own
users, this one involves a third party — a venue owner, a named person — who
has no relationship with the platform and a direct cause of action. A small
beta can run with weak Sybil resistance; publishing unremovable user-supplied
text about real named businesses is a different bet.


---

## Implementation status (Phase 3)

Every invariant above has at least one executable test in
`server/tests/test_privacy_invariants.py`, and that property is itself enforced
by `test_every_documented_invariant_has_a_test`, which parses this file for
`INV-` headings and fails if any lacks a matching test name. Adding an
invariant here without covering it breaks the build, by design.

Several invariants constrain layers that do not exist yet — there is one route
(`/health`) and no repository at all. Those are covered by assertions of
absence over the mapped tables, the generated OpenAPI schema, and the `app/`
source tree, per the "MUST NOT exist" rule at the top of this file. They are
written to fail on the commit that introduces the breach rather than to be
revisited when the layer arrives. The absence tests were verified by planting
deliberate breaches — a user-indexed contribution lookup, a venue search, a
consent delete, a `GET /contributions/{id}` route, a payload in a log line, a
`free_text` column, a `signed_url` column, a removed threshold check, and an
age check defaulting open — and confirming each was caught.

### Modules beyond the Phase 3 instruction

`docs/00_BOOTSTRAP.md` names `services/aggregation.py` and
`services/privacy_gate.py`. Two further modules were added, both pure functions
over existing domain models, because the invariants they serve are positive
"must fail closed" requirements that cannot be tested by asserting absence:

- **`services/consent.py`** — `INV-CONSENT-1`, `INV-CONSENT-4` and
  `INV-MINOR-1` all require the import path to refuse by default. A refusal
  rule with nothing callable behind it is an aspiration, and writing the gate
  before the import flow means the flow has to come through it.
- **`services/place_cache.py`** — `INV-CACHE-1` requires expired coordinate
  entries to be *purged*, and `INV-CACHE-2` requires the read path to refetch
  rather than serve stale. Both are behaviour, not schema.

Neither adds a dependency, a table, an endpoint, or a persisted field. In
particular, `consent.py` takes age eligibility as a call-time argument rather
than storing it: whether anything about a user's age may be persisted is a
retention decision reserved to the owner, and `User` is unchanged.

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
