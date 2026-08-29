"""
app/domain/models.py
--------------------
Pydantic domain models: the in-memory representation from
docs/02_DOMAIN_MODEL.md.

These are data plus pure queries over their own state. Anything that mutates
across entities -- folding a contribution into an aggregate, purging it,
applying the privacy gate -- belongs in services/, not here (Phase 3).

Two parameters that other systems would hand you as defaults are required
arguments in this module instead: the coordinate retention window
(PlaceRef.needs_refresh) and the cohort bucketing policy
(CommunityAggregate.to_public_view). Both are open decisions in
docs/04_PRIVACY_INVARIANTS.md, and a plausible-looking default is exactly how
an open decision silently becomes a shipped one.
"""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import (
    CommunityStatus,
    Confidence,
    ConsentScope,
    ContributionSource,
    FacetValueType,
    ImportJobState,
    Tier,
)

# COMPLETE -> EXPIRED after 14 days (docs/02_DOMAIN_MODEL.md, report 6.7.1).
ARCHIVE_RETENTION = timedelta(days=14)

# FAILED -> PENDING while retry_count < 3 (same source).
MAX_IMPORT_RETRIES = 3


# ── Persisted entities ────────────────────────────────────────────────────────


class User(BaseModel):
    """Pseudonymous. Carries no directly identifying fields, deliberately.

    If authentication later needs a link to an external identity, it goes in a
    separate table with its own justification -- not here. See CLAUDE.md and
    docs/01_STACK_DECISIONS.md on why a phone number was considered and
    rejected.
    """

    user_id: UUID = Field(default_factory=uuid4)
    created_at: datetime


class Community(BaseModel):
    community_id: UUID = Field(default_factory=uuid4)
    slug: str
    # No default. OPEN-1: no safe value exists; it must be set per community by
    # a documented decision.
    min_cohort_threshold: int
    status: CommunityStatus
    created_at: datetime

    def can_go_live(self, current_cohort: int) -> bool:
        """Whether the community has enough members to publish anything."""
        return current_cohort >= self.min_cohort_threshold


class CommunityMembership(BaseModel):
    """Tier is per-membership: one may found one community and join another."""

    membership_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    community_id: UUID
    tier: Tier
    joined_at: datetime


class Facet(BaseModel):
    """Owned by a community (composition).

    The mechanism only. Which facets a wine-lover rates versus a cricketer is
    an unspecified design pass -- see docs/02_DOMAIN_MODEL.md.
    """

    facet_id: UUID = Field(default_factory=uuid4)
    community_id: UUID
    name: str
    value_type: FacetValueType
    scale_min: float | None = None
    scale_max: float | None = None


class ConsentRecord(BaseModel):
    """Append-only. Revocation writes revoked_at; nothing rewrites or deletes.

    The history of what was consented to, and when, is itself the audit trail
    (INV-CONSENT-2).
    """

    consent_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    scope: ConsentScope
    granted_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        """Active means granted, not revoked, and not expired, as at `now`."""
        if self.revoked_at is not None and self.revoked_at <= now:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return self.granted_at <= now


class GoogleImportJob(BaseModel):
    """Archive lifecycle as queryable state rather than transient control flow.

    Note the absence of a signed-URL field: INV-CONSENT-3 requires that signed
    URLs are held in memory for the download only and never persisted. Only the
    expiry instant is recorded.
    """

    job_id: str
    user_id: UUID
    consent_id: UUID
    state: ImportJobState
    initiated_at: datetime
    completed_at: datetime | None = None
    signed_url_expires_at: datetime | None = None
    retry_count: int = 0

    def is_expired(self, now: datetime) -> bool:
        """Whether this job is past its usable life.

        Expired if already marked so, if the signed URL's expiry has passed, or
        if the archive has been complete for longer than ARCHIVE_RETENTION.
        """
        if self.state is ImportJobState.EXPIRED:
            return True
        if self.signed_url_expires_at is not None and now >= self.signed_url_expires_at:
            return True
        return self.completed_at is not None and now >= self.completed_at + ARCHIVE_RETENTION

    def can_retry(self) -> bool:
        """FAILED -> PENDING is permitted while retry_count is under the cap."""
        return self.state is ImportJobState.FAILED and self.retry_count < MAX_IMPORT_RETRIES


class PlaceRef(BaseModel):
    """A pointer into Google's catalogue plus refresh bookkeeping.

    Not a venue database, and must not grow into one: no name, address, rating,
    photos, opening hours, or review text (INV-CACHE-1).
    """

    place_id: str
    last_refreshed_at: datetime
    cached_lat: float | None = None
    cached_lng: float | None = None
    coords_cached_at: datetime | None = None

    def needs_refresh(self, now: datetime, coord_retention: timedelta) -> bool:
        """Whether cached coordinates must be treated as absent and refetched.

        `coord_retention` is a required argument rather than a constant because
        the cacheable window is set by Google's then-current Places policy,
        which changes -- see the warning under INV-CACHE-2. Stale coordinates
        must never be served (INV-CACHE-2), so absent cache metadata counts as
        needing a refresh.
        """
        if self.coords_cached_at is None:
            return True
        return now >= self.coords_cached_at + coord_retention


class FacetStat(BaseModel):
    """Owned by an aggregate (composition).

    Placeholder shape. A mean/variance/n triple stands in until the privacy
    mechanism is chosen; differential privacy generally requires the
    aggregation function to be fixed before noise can be calibrated (OPEN-3).
    Do not build anything that assumes this shape is final.
    """

    facet_id: UUID
    mean: float
    variance: float
    n: int


class CohortBucketing(BaseModel):
    """Maps an exact cohort size onto a published bucket label.

    Deliberately has no default instance. Publishing exact counts across
    successive releases is what enables a differencing attack (INV-EXPOSE-2,
    OPEN-2), so the boundaries are a privacy parameter and belong to the
    project owner, not to an implementer picking something reasonable-looking.
    """

    model_config = ConfigDict(frozen=True)

    # Ascending lower bounds, e.g. (0, 10, 25, 50, 100) -> "0-9", "10-24",
    # "25-49", "50-99", "100+".
    boundaries: tuple[int, ...]

    @field_validator("boundaries")
    @classmethod
    def _ascending_and_zero_based(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("boundaries must not be empty")
        if value[0] != 0:
            raise ValueError("boundaries must start at 0")
        if list(value) != sorted(set(value)):
            raise ValueError("boundaries must be strictly ascending with no duplicates")
        return value

    def label(self, cohort_size: int) -> str:
        """Bucket label for a cohort size. Never returns the exact figure."""
        if cohort_size < 0:
            raise ValueError("cohort_size must not be negative")
        for lower, upper in zip(self.boundaries, self.boundaries[1:], strict=False):
            if cohort_size < upper:
                return f"{lower}-{upper - 1}"
        return f"{self.boundaries[-1]}+"


class PublicAggregateView(BaseModel):
    """The only shape that leaves the system.

    Carries cohort_size_bucket and never cohort_size (INV-EXPOSE-2), and no
    string field capable of holding review prose (INV-RAW-3).
    """

    community_id: UUID
    place_id: str
    facet_summaries: list[FacetStat]
    cohort_size_bucket: str


class CommunityAggregate(BaseModel):
    """The durable product: a community's taste-weighted signal for a place.

    `apply_contribution` from docs/02_DOMAIN_MODEL.md is deliberately absent
    here. Folding is incremental aggregation across entities and lives in
    services/aggregation.py (Phase 3); these models stay data.

    Must not be serialised to an API response directly -- only
    PublicAggregateView may leave the system (INV-EXPOSE-5).
    """

    aggregate_id: UUID = Field(default_factory=uuid4)
    community_id: UUID
    place_id: str
    facet_stats: dict[UUID, FacetStat] = Field(default_factory=dict)
    cohort_size: int = 0
    last_updated_at: datetime
    noise_epsilon: float | None = None

    def is_above_threshold(self, min_cohort: int) -> bool:
        return self.cohort_size >= min_cohort

    def to_public_view(self, bucketing: CohortBucketing) -> PublicAggregateView:
        """Project to the publishable shape.

        This is a projection, not a privacy decision: it does not check the
        threshold. Suppression is PrivacyGate's job and is applied on every
        read (INV-EXPOSE-4), so callers must gate before publishing.
        """
        return PublicAggregateView(
            community_id=self.community_id,
            place_id=self.place_id,
            facet_summaries=list(self.facet_stats.values()),
            cohort_size_bucket=bucketing.label(self.cohort_size),
        )


# ── Transient entity ──────────────────────────────────────────────────────────


class RawContribution(BaseModel):
    """The only structure carrying identified per-person data.

    Never persisted. There is no SQLAlchemy table for this model and no
    repository that stores one -- see the "RawContribution persistence"
    section of docs/02_DOMAIN_MODEL.md for the reasoning.

    `fold_into` and `purge` are behaviour and live in services/aggregation.py
    (Phase 3), not on this model.
    """

    contribution_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    community_id: UUID
    place_id: str
    facet_scores: dict[UUID, float]
    # Highest-identifiability field on a contribution: writing style and
    # specific detail are effectively a fingerprint. Consumed during
    # normalisation, never persisted to the aggregate layer (INV-RAW-3).
    free_text: str | None = None
    source: ContributionSource
    confidence: Confidence
    source_job_id: str | None = None
    captured_at: datetime
    folded_at: datetime | None = None
