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
- Behaviour: `needs_refresh(now) -> bool`

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
  `apply_contribution(c) -> None`, `to_public_view() -> PublicAggregateView`

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

Governed by invariants `INV-RAW-1` and `INV-RAW-2`. Whatever persistence
approach is chosen in Phase 2, a raw contribution must not remain readable after
it has been folded.

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

## Relationships

```
User            1 ──── 0..* CommunityMembership *──── 1 Community
Community       1 ──◆── 0..* Facet                       (composition)
Community       1 ──── 0..* CommunityAggregate
ConsentRecord   1 ──── 0..* GoogleImportJob
RawContribution 0..* ──── 1 PlaceRef
RawContribution 0..* ──── 1 CommunityAggregate           (folds into)
CommunityAggregate 1 ──◆── 0..* FacetStat                (composition)
CommunityAggregate 1 ──── 0..1 PublicAggregateView       (publishes as)
```
