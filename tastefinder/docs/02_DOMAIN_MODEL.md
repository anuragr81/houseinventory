# 02 — Domain Model

Derived from the UML in Section 6 of the design report. That report is the
source of truth for *why* the model has this shape; this document is the source
of truth for *what to implement*.

Field names below are the contract. If you rename one, update this file in the
same commit.

## Enums

| Enum | Values |
|---|---|
| `Tier` | `FOUNDER`, `JOINER` |
| `CommunityStatus` | `SEEDING`, `LIVE` |
| `FacetValueType` | `NUMERIC`, `ORDINAL`, `BOOLEAN`, `TEXT` |
| `ConsentScope` | `DIRECT_CURATION`, `GOOGLE_IMPORT_ONE_TIME`, `GOOGLE_IMPORT_TIME_BOUNDED` |
| `ImportJobState` | `INITIATED`, `PENDING`, `COMPLETE`, `FAILED`, `EXPIRED` |
| `ContributionSource` | `DIRECT`, `GOOGLE_IMPORT` |
| `Confidence` | `STATED`, `INFERRED` |

## Persisted entities

### `User`
Pseudonymous. Carries **no** directly identifying fields — no name, no email, no
Google account ID, no phone number. If authentication later needs a link to an
external identity, it goes in a separate table with its own justification, not
here.

- `user_id: UUID` (PK)
- `created_at: datetime`

### `IdentityLink` (added, Auth Part 1)
The separate table `User`'s docstring promised. Maps a Google account back to
a `user_id`, and holds nothing else.

- `subject_hash: str` (PK) — `HMAC-SHA256(server_pepper, google_sub)`, hex.
  Never the Google `sub` itself (`INV-AUTH-1`).
- `user_id: UUID` (FK → User)
- `created_at: datetime`

No email, name, picture, or raw ID token. Computing `subject_hash` is
`services/auth.py`'s job (`hash_subject`); this table only stores the result.
See `docs/05_AUTH_DESIGN.md`.

### `AuthSession` (added, Auth Part 1)
A server-issued bearer session, hashed at rest for the same reason
`IdentityLink` hashes the Google `sub`: a database leak should not hand out
usable credentials.

- `token_hash: str` (PK) — SHA-256 of the bearer token, hex.
- `user_id: UUID` (FK → User)
- `created_at: datetime`
- `expires_at: datetime`
- Behaviour: `is_active(now: datetime) -> bool`

The raw token is generated in `services/auth.py` (`generate_session_token`)
and returned to the client exactly once, at issuance (`POST /auth/google`).
It is never persisted, logged, or retrievable again — only its hash is.

### `CommunityMembership`
Tier is per-membership, not per-user: someone may found one community and merely
join another.

- `membership_id: UUID` (PK)
- `user_id: UUID` (FK → User)
- `community_id: UUID` (FK → Community)
- `tier: Tier`
- `joined_at: datetime`

### `Community`
- `community_id: UUID` (PK)
- `slug: str` (unique)
- `min_cohort_threshold: int`
- `status: CommunityStatus`
- `created_at: datetime`
- Behaviour: `can_go_live(current_cohort: int) -> bool`

`min_cohort_threshold` has **no default value.** It must be set explicitly per
community. Do not seed it with a plausible-looking number.

### `Facet`
Owned by a community (composition — deleting a community deletes its facets).

- `facet_id: UUID` (PK)
- `community_id: UUID` (FK → Community)
- `name: str`
- `value_type: FacetValueType`
- `scale_min: Optional[float]`
- `scale_max: Optional[float]`

The actual facet sets per community (what a wine-lover rates vs. a cricketer)
are **not specified yet** and need their own design pass. Build the mechanism,
not the content.

### `ConsentRecord`
- `consent_id: UUID` (PK)
- `user_id: UUID` (FK → User)
- `scope: ConsentScope`
- `granted_at: datetime`
- `expires_at: Optional[datetime]`
- `revoked_at: Optional[datetime]`
- Behaviour: `is_active(now: datetime) -> bool`

Consent records are **append-only**. Revocation sets `revoked_at`; it never
deletes or rewrites the row. The history of what was consented to and when is
itself the audit trail.

### `GoogleImportJob`
Tracks the asynchronous archive lifecycle so retries and expiry are queryable
state rather than transient control flow.

- `job_id: str` (PK — Google's job ID)
- `user_id: UUID` (FK → User)
- `consent_id: UUID` (FK → ConsentRecord)
- `state: ImportJobState`
- `initiated_at: datetime`
- `completed_at: Optional[datetime]`
- `signed_url_expires_at: Optional[datetime]`
- `retry_count: int`
- Behaviour: `is_expired(now) -> bool`, `can_retry() -> bool`

State machine (report §6.7.1): `INITIATED → PENDING`; `PENDING → COMPLETE` or
`PENDING → FAILED`; `FAILED → PENDING` while `retry_count < 3`;
`COMPLETE → EXPIRED` after 14 days or once the archive is consumed.

A signed URL must **never** be persisted in this table. Hold it in memory for the
duration of the download only.

### `PlaceRef`
The platform's only venue record: a pointer into Google's catalogue plus refresh
bookkeeping. It is not a venue database and must not grow into one.

- `place_id: str` (PK — Google place ID)
- `last_refreshed_at: datetime`
- `cached_lat: Optional[float]`
- `cached_lng: Optional[float]`
- `coords_cached_at: Optional[datetime]`
- Behaviour: `needs_refresh(now, coord_retention) -> bool`

> **Signature note (Phase 2).** `needs_refresh` takes the retention window as a
> required argument rather than reading a module constant. The cacheable window
> is set by Google's then-current Places policy and changes; the warning under
> `INV-CACHE-2` says to treat it as something to re-verify, not a constant.
> Making it an argument means it cannot quietly harden into one. Absent
> `coords_cached_at` counts as needing a refresh, so stale coordinates are never
> served.

Do **not** add columns for name, address, rating, photos, opening hours, or
review text. See invariant `INV-CACHE-1` in `docs/04`.

### `CommunityAggregate`
- `aggregate_id: UUID` (PK)
- `community_id: UUID` (FK → Community)
- `place_id: str` (FK → PlaceRef)
- `facet_stats: Mapping[UUID, FacetStat]`
- `cohort_size: int`
- `last_updated_at: datetime`
- `noise_epsilon: Optional[float]`
- Behaviour: `is_above_threshold(min_cohort) -> bool`,
  `to_public_view(bucketing) -> PublicAggregateView`

> **Signature notes (Phase 2).** `apply_contribution` is **not** implemented on
> this model. Phase 2's instruction is to keep the domain models as data and put
> folding in `services/aggregation.py`; folding is incremental aggregation
> across entities, so it lives there with `fold_into`/`purge` rather than being
> split across two layers.
>
> `to_public_view` takes an explicit `CohortBucketing` (below). It is a
> projection, not a privacy decision — it does not check the threshold, because
> suppression is `PrivacyGate`'s job and `INV-EXPOSE-4` requires it on every
> read. Callers must gate before publishing.

### `FacetStat`
Owned by an aggregate (composition).

- `facet_id: UUID`
- `mean: float`
- `variance: float`
- `n: int`

**Placeholder.** A mean/variance/n triple is a stand-in until the privacy
mechanism is chosen — differential privacy generally requires the aggregation
function to be fixed before noise can be calibrated. Do not build anything that
assumes this shape is final.

## Transient entity

### `RawContribution`
The **only** structure carrying identified per-person data. It exists to be
folded and then destroyed.

- `contribution_id: UUID`
- `user_id: UUID`
- `community_id: UUID`
- `place_id: str`
- `facet_scores: Mapping[UUID, float]`
- `free_text: Optional[str]`
- `source: ContributionSource`
- `confidence: Confidence`
- `source_job_id: Optional[str]`
- `captured_at: datetime`
- `folded_at: Optional[datetime]`
- Behaviour (implement in `services/aggregation.py`, not on the model):
  `fold_into(target)`, `purge()`

> **Signature note (Phase 3).** Implemented as
> `StreamingAggregator.fold(contribution, aggregate, now)` and a module-level
> `purge(contribution)`, rather than as `fold_into` on a contribution object.
> Folding reads and writes both entities, so naming it after one of them
> misdescribes it; the aggregator is also the seam `docs/00_BOOTSTRAP.md`
> expects later phases to replace for batched updates (`OPEN-2`) or a different
> statistic (`OPEN-3`).
>
> `fold` purges the contribution on **every** exit path, success or failure.
> A rejected contribution therefore cannot be corrected and resubmitted from
> the object that was passed in. That is the cost of the transience rule in
> `CLAUDE.md`, paid deliberately: a failed fold holding identified data in
> memory indefinitely is the thing `INV-RAW-1` exists to prevent.
>
> `cohort_size` counts contributions, not distinct contributors — see `OPEN-7`
> in `docs/04_PRIVACY_INVARIANTS.md`, which is a genuine open question about the
> suppression threshold rather than a naming detail.

Governed by invariants `INV-RAW-1` and `INV-RAW-2`. Whatever persistence
approach is chosen in Phase 2, a raw contribution must not remain readable after
it has been folded.

### RawContribution persistence — decision (Phase 2)

**Chosen: an in-flight object. `RawContribution` is never persisted. There is no
table for it, and `Base.metadata` contains none.**

Phase 2 offered two options: a short-lived working row with a `folded_at` column
and a hard deletion path, or an in-flight object. The second is stronger, and
the reasoning is worth keeping because the first will look tempting again later:

- **A working table cannot satisfy `INV-RAW-2` during its own lifetime.** Such a
  row necessarily holds `user_id` beside `facet_scores` — precisely the shape the
  invariant forbids. The invariant is written as "after folding", but a table
  whose steady state is a breach relies on deletion always succeeding to stay
  compliant, which is a weaker guarantee than never writing the row.
- **Deletion is not erasure.** A hard `DELETE` leaves data recoverable in
  database backups, WAL segments, and page slack. "Purged" would mean
  "unreachable through the ORM", not "gone" — and `INV-RAW-1` is about what
  survives, not what is convenient to query.
- **A crash becomes a retention event.** If the process dies between capture and
  fold, a working table keeps identified rows on disk indefinitely with no
  actor responsible for clearing them. An in-memory object simply ceases to
  exist.
- **`docs/04` names this exact instinct.** "Keep raw contributions
  'temporarily' to make aggregation easier to test" is listed under *For the
  agent* as a direct breach. The convenience is real; that is why it is written
  down.

**What this costs, stated plainly.** A contribution that arrives and is not
folded before the process dies is lost, with no durable queue to replay it from.
That is an availability cost, paid deliberately, because `CLAUDE.md` makes
transience of identified data the rule that overrides everything else. If that
trade is ever judged wrong, the alternative is not a raw-contribution table but
a durable *aggregate-side* write-ahead of the fold operation, which keeps the
identified payload out of storage entirely. **That would be the project owner's
decision to make, not an implementer's.**

`folded_at` is retained on the in-memory model. It marks that folding has run so
that Phase 3 can detect a double-fold, and it never reaches a database.

## Output type

### `PublicAggregateView`
The only shape that leaves the system.

- `community_id: UUID`
- `place_id: str`
- `facet_summaries: list[FacetStat]`
- `cohort_size_bucket: str`  — e.g. `"10-24"`

`cohort_size_bucket`, never `cohort_size`. Publishing exact counts across
successive releases is what enables a differencing attack; bucketing is the
first line of defence against it. See `INV-EXPOSE-2`.

### `CohortBucketing` (added in Phase 2)

Maps an exact cohort size onto a published bucket label. Added because
`PublicAggregateView.cohort_size_bucket` needs something to produce it, and the
bucket boundaries are a privacy parameter rather than a formatting detail.

- `boundaries: tuple[int, ...]` — ascending lower bounds, must start at 0
- Behaviour: `label(cohort_size) -> str`

Example: `(0, 10, 25, 50, 100)` yields `"0-9"`, `"10-24"`, `"25-49"`, `"50-99"`,
`"100+"`.

**There is deliberately no default instance and no default boundary set.** Bucket
width determines how much a published figure narrows an attacker's estimate of a
cohort, so it is the same class of decision as `min_cohort_threshold` under
`OPEN-1` and the mechanism parameters under `OPEN-3` — one for the project owner,
recorded, not picked by an implementer because it looked reasonable. The tuple
above is an illustration in this document, not a default in the code.

## Relationships

```
User            1 ──── 0..1 IdentityLink                (Auth Part 1)
User            1 ──── 0..* AuthSession                  (Auth Part 1)
User            1 ──── 0..* CommunityMembership *──── 1 Community
Community       1 ──◆── 0..* Facet                       (composition)
Community       1 ──── 0..* CommunityAggregate
ConsentRecord   1 ──── 0..* GoogleImportJob
RawContribution 0..* ──── 1 PlaceRef
RawContribution 0..* ──── 1 CommunityAggregate           (folds into)
CommunityAggregate 1 ──◆── 0..* FacetStat                (composition)
CommunityAggregate 1 ──── 0..1 PublicAggregateView       (publishes as)
```
