"""
app/domain/enums.py
-------------------
Enumerations from docs/02_DOMAIN_MODEL.md.

Implemented first because everything else references them. StrEnum so that
values serialise as their own names in JSON and OpenAPI, which keeps the
generated Dart client readable.
"""

from enum import StrEnum


class Tier(StrEnum):
    """Membership tier. Per-membership, not per-user."""

    FOUNDER = "FOUNDER"
    JOINER = "JOINER"


class CommunityStatus(StrEnum):
    SEEDING = "SEEDING"
    LIVE = "LIVE"


class FacetValueType(StrEnum):
    NUMERIC = "NUMERIC"
    ORDINAL = "ORDINAL"
    BOOLEAN = "BOOLEAN"
    TEXT = "TEXT"


class ConsentScope(StrEnum):
    DIRECT_CURATION = "DIRECT_CURATION"
    GOOGLE_IMPORT_ONE_TIME = "GOOGLE_IMPORT_ONE_TIME"
    GOOGLE_IMPORT_TIME_BOUNDED = "GOOGLE_IMPORT_TIME_BOUNDED"


class ImportJobState(StrEnum):
    """Google archive lifecycle. Transitions in docs/02_DOMAIN_MODEL.md."""

    INITIATED = "INITIATED"
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ContributionSource(StrEnum):
    DIRECT = "DIRECT"
    GOOGLE_IMPORT = "GOOGLE_IMPORT"


class Confidence(StrEnum):
    STATED = "STATED"
    INFERRED = "INFERRED"
