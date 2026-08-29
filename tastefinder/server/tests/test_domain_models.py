"""
tests/test_domain_models.py
---------------------------
Phase 2 checks on the domain models' own behaviour.

The privacy-invariant suite proper (one test per INV- id) is Phase 3 and lives
in tests/test_privacy_invariants.py. What is here is ordinary unit testing of
the model layer, plus the structural assertions that Phase 2 itself creates the
risk of getting wrong.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.enums import (
    CommunityStatus,
    Confidence,
    ConsentScope,
    ContributionSource,
    ImportJobState,
)
from app.domain.models import (
    ARCHIVE_RETENTION,
    CohortBucketing,
    Community,
    CommunityAggregate,
    ConsentRecord,
    FacetStat,
    GoogleImportJob,
    PlaceRef,
    RawContribution,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _community(threshold: int = 10) -> Community:
    return Community(
        slug="wine",
        min_cohort_threshold=threshold,
        status=CommunityStatus.SEEDING,
        created_at=NOW,
    )


# ── Community ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cohort", "expected"),
    [(0, False), (9, False), (10, True), (11, True)],
)
def test_can_go_live_is_inclusive_at_the_threshold(cohort: int, expected: bool) -> None:
    assert _community(10).can_go_live(cohort) is expected


def test_min_cohort_threshold_has_no_default() -> None:
    """OPEN-1: no safe default exists, so construction must demand one."""
    with pytest.raises(ValueError, match="min_cohort_threshold"):
        Community(  # type: ignore[call-arg]
            slug="wine", status=CommunityStatus.SEEDING, created_at=NOW
        )


# ── ConsentRecord ─────────────────────────────────────────────────────────────


def test_consent_is_active_when_granted_and_unrevoked() -> None:
    record = ConsentRecord(
        user_id=uuid4(), scope=ConsentScope.DIRECT_CURATION, granted_at=NOW - timedelta(days=1)
    )
    assert record.is_active(NOW) is True


def test_consent_is_inactive_once_revoked() -> None:
    record = ConsentRecord(
        user_id=uuid4(),
        scope=ConsentScope.GOOGLE_IMPORT_ONE_TIME,
        granted_at=NOW - timedelta(days=2),
        revoked_at=NOW - timedelta(days=1),
    )
    assert record.is_active(NOW) is False


def test_consent_is_inactive_once_expired() -> None:
    record = ConsentRecord(
        user_id=uuid4(),
        scope=ConsentScope.GOOGLE_IMPORT_TIME_BOUNDED,
        granted_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(seconds=1),
    )
    assert record.is_active(NOW) is False


# ── GoogleImportJob ───────────────────────────────────────────────────────────


def _job(**overrides: object) -> GoogleImportJob:
    base: dict[str, object] = {
        "job_id": "g-1",
        "user_id": uuid4(),
        "consent_id": uuid4(),
        "state": ImportJobState.PENDING,
        "initiated_at": NOW,
    }
    base.update(overrides)
    return GoogleImportJob(**base)  # type: ignore[arg-type]


def test_job_expires_after_the_archive_retention_window() -> None:
    job = _job(state=ImportJobState.COMPLETE, completed_at=NOW)
    assert job.is_expired(NOW + ARCHIVE_RETENTION - timedelta(seconds=1)) is False
    assert job.is_expired(NOW + ARCHIVE_RETENTION) is True


def test_job_expires_when_the_signed_url_expiry_passes() -> None:
    job = _job(signed_url_expires_at=NOW + timedelta(hours=1))
    assert job.is_expired(NOW) is False
    assert job.is_expired(NOW + timedelta(hours=1)) is True


@pytest.mark.parametrize(
    ("state", "retries", "expected"),
    [
        (ImportJobState.FAILED, 0, True),
        (ImportJobState.FAILED, 2, True),
        (ImportJobState.FAILED, 3, False),
        (ImportJobState.PENDING, 0, False),
        (ImportJobState.COMPLETE, 0, False),
    ],
)
def test_can_retry_only_from_failed_and_under_the_cap(
    state: ImportJobState, retries: int, expected: bool
) -> None:
    assert _job(state=state, retry_count=retries).can_retry() is expected


def test_import_job_has_no_signed_url_field() -> None:
    """INV-CONSENT-3: the URL is held in memory for the download only."""
    assert not [f for f in GoogleImportJob.model_fields if "url" in f and f.endswith("url")]


# ── PlaceRef ──────────────────────────────────────────────────────────────────


def test_uncached_coordinates_always_need_refresh() -> None:
    place = PlaceRef(place_id="p1", last_refreshed_at=NOW)
    assert place.needs_refresh(NOW, timedelta(days=30)) is True


def test_coordinates_need_refresh_once_past_retention() -> None:
    place = PlaceRef(
        place_id="p1", last_refreshed_at=NOW, cached_lat=1.0, cached_lng=2.0, coords_cached_at=NOW
    )
    window = timedelta(days=30)
    assert place.needs_refresh(NOW + window - timedelta(seconds=1), window) is False
    assert place.needs_refresh(NOW + window, window) is True


def test_place_ref_holds_no_display_fields() -> None:
    """INV-CACHE-1: name, address, rating, photos, hours, review text."""
    forbidden = {"name", "formatted_address", "address", "rating", "photos", "opening_hours",
                 "reviews", "review_text"}
    assert not forbidden & set(PlaceRef.model_fields)


# ── Cohort bucketing and the public view ──────────────────────────────────────


def test_bucketing_rejects_boundaries_that_do_not_start_at_zero() -> None:
    with pytest.raises(ValueError, match="start at 0"):
        CohortBucketing(boundaries=(10, 25))


def test_bucketing_rejects_non_ascending_boundaries() -> None:
    with pytest.raises(ValueError, match="ascending"):
        CohortBucketing(boundaries=(0, 25, 10))


@pytest.mark.parametrize(
    ("cohort", "expected"),
    [(0, "0-9"), (9, "0-9"), (10, "10-24"), (24, "10-24"), (25, "25-49"), (100, "100+")],
)
def test_bucket_labels(cohort: int, expected: str) -> None:
    bucketing = CohortBucketing(boundaries=(0, 10, 25, 50, 100))
    assert bucketing.label(cohort) == expected


def test_public_view_carries_a_bucket_and_never_the_exact_count() -> None:
    """INV-EXPOSE-2, checked here because Phase 2 defines the projection."""
    aggregate = CommunityAggregate(
        community_id=uuid4(),
        place_id="p1",
        cohort_size=37,
        last_updated_at=NOW,
        facet_stats={},
    )
    view = aggregate.to_public_view(CohortBucketing(boundaries=(0, 10, 25, 50, 100)))
    assert view.cohort_size_bucket == "25-49"
    assert "cohort_size" not in view.model_dump()
    assert "37" not in view.model_dump_json()


def test_public_view_has_no_free_text_field() -> None:
    """INV-RAW-3: no string field capable of holding review prose."""
    string_fields = {
        name
        for name, field in type(
            CommunityAggregate(
                community_id=uuid4(), place_id="p", last_updated_at=NOW
            ).to_public_view(CohortBucketing(boundaries=(0, 10)))
        ).model_fields.items()
        if field.annotation is str
    }
    # place_id and the bucket label are the only strings, and neither can hold prose.
    assert string_fields == {"place_id", "cohort_size_bucket"}


def test_aggregate_threshold_check_is_inclusive() -> None:
    aggregate = CommunityAggregate(
        community_id=uuid4(), place_id="p1", cohort_size=10, last_updated_at=NOW
    )
    assert aggregate.is_above_threshold(10) is True
    assert aggregate.is_above_threshold(11) is False


def test_aggregate_has_no_apply_contribution_method() -> None:
    """Folding is aggregation logic and belongs in services/ (Phase 3)."""
    assert not hasattr(CommunityAggregate, "apply_contribution")


# ── RawContribution ───────────────────────────────────────────────────────────


def test_raw_contribution_carries_folding_behaviour_nowhere_on_the_model() -> None:
    """fold_into/purge are services/aggregation.py in Phase 3, not ORM methods."""
    assert not hasattr(RawContribution, "fold_into")
    assert not hasattr(RawContribution, "purge")


def test_raw_contribution_is_constructible_in_memory() -> None:
    contribution = RawContribution(
        user_id=uuid4(),
        community_id=uuid4(),
        place_id="p1",
        facet_scores={uuid4(): 4.5},
        source=ContributionSource.DIRECT,
        confidence=Confidence.STATED,
        captured_at=NOW,
    )
    assert contribution.folded_at is None
    assert contribution.free_text is None


def test_facet_stat_is_the_placeholder_triple() -> None:
    """OPEN-3: nothing may assume this shape is final, but it is what exists."""
    assert set(FacetStat.model_fields) == {"facet_id", "mean", "variance", "n"}
