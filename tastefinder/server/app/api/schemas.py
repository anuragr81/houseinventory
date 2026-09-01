"""
app/api/schemas.py
-------------------
Request and response shapes for the routes, matching `docs/03_API_CONTRACT.md`
exactly rather than serialising or deserialising domain models directly.

A domain model's shape is free to grow -- `Community` already carries
`min_cohort_threshold` and `created_at`, which the contract deliberately
excludes from both `GET /communities` and `GET /communities/{slug}`. An API
schema is a promise about the wire format; it must not drift with the domain
model by accident just because they happen to share fields today.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import CommunityStatus, FacetValueType


class FacetOut(BaseModel):
    """One entry in the platform's facet catalogue (`GET /facets`)."""

    key: str
    name: str
    value_type: FacetValueType
    scale_min: float | None
    scale_max: float | None


class CommunityFacetOut(BaseModel):
    """One of a specific community's facets, as founding created it."""

    facet_id: UUID
    name: str
    value_type: FacetValueType
    scale_min: float | None
    scale_max: float | None


class CommunitySummaryOut(BaseModel):
    """`GET /communities` list entry. Never cohort_size or membership."""

    community_id: UUID
    slug: str
    status: CommunityStatus


class CommunityDetailOut(BaseModel):
    """`GET /communities/{slug}`. Still no cohort_size, still no aggregates."""

    community_id: UUID
    slug: str
    status: CommunityStatus
    facets: list[CommunityFacetOut]


class FacetStatOut(BaseModel):
    """One facet's summary within a published aggregate. Never cohort_size."""

    facet_id: UUID
    mean: float
    variance: float
    n: int


class AggregateOut(BaseModel):
    """`GET /communities/{slug}/places/{place_id}/aggregate`.

    Mirrors `PublicAggregateView` field-for-field rather than reusing it
    directly -- same reasoning as the schemas above: the wire format is a
    promise independent of how the domain model happens to be shaped today.
    Never carries `cohort_size`, only `cohort_size_bucket` (`INV-EXPOSE-2`).
    """

    community_id: UUID
    place_id: str
    facet_summaries: list[FacetStatOut]
    cohort_size_bucket: str


class GoogleSignInIn(BaseModel):
    """`POST /auth/google` request body: the ID token the client already
    obtained from native Google Sign-In. Nothing else -- the server reads no
    other field off the client's OAuth exchange."""

    id_token: str


class SessionOut(BaseModel):
    """`POST /auth/google` response: the bearer token and its expiry.

    The only place the raw session token ever appears -- it is not
    retrievable again, and the server persists only its hash
    (`app/services/auth.py`).
    """

    session_token: str
    expires_at: datetime


class FoundingContributionIn(BaseModel):
    """One rating in a `POST /communities` founding batch."""

    place_id: str
    facet_scores: dict[str, float]
    free_text: str | None = None


class FoundCommunityIn(BaseModel):
    """`POST /communities` request body. `facet_keys` selects from the
    platform's catalogue (`GET /facets`); a founder cannot author a facet
    name (`INV-SCHEMA-1`)."""

    slug: str
    min_cohort_threshold: int
    facet_keys: list[str]
    contributions: list[FoundingContributionIn]
