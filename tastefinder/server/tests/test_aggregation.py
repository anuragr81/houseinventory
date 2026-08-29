"""
tests/test_aggregation.py
-------------------------
Behaviour of the streaming aggregator, separate from the invariant suite.

The invariants in tests/test_privacy_invariants.py check that folding does not
*leak*. What is here checks that it is *correct* -- that the incremental
statistics match what a batch computation over the same observations would
produce. Both matter: an aggregator that leaks nothing and computes the wrong
mean is still useless, and there are no stored raw contributions to recompute
from once it has drifted.
"""

import logging
import math
import statistics
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain.enums import Confidence, ContributionSource
from app.domain.models import CommunityAggregate, RawContribution
from app.services.aggregation import (
    NIL_UUID,
    AlreadyFoldedError,
    InvalidScoreError,
    MismatchedAggregateError,
    StreamingAggregator,
    is_purged,
    purge,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
COMMUNITY_ID = uuid4()
PLACE_ID = "ChIJ_aggregation_test_place"
FACET_A = uuid4()
FACET_B = uuid4()


def _aggregate() -> CommunityAggregate:
    return CommunityAggregate(
        community_id=COMMUNITY_ID, place_id=PLACE_ID, last_updated_at=NOW
    )


def _contribution(
    scores: dict[UUID, float],
    *,
    community_id: UUID | None = None,
    place_id: str = PLACE_ID,
    free_text: str | None = None,
) -> RawContribution:
    return RawContribution(
        user_id=uuid4(),
        community_id=community_id or COMMUNITY_ID,
        place_id=place_id,
        facet_scores=scores,
        free_text=free_text,
        source=ContributionSource.DIRECT,
        confidence=Confidence.STATED,
        captured_at=NOW,
    )


def _fold_all(values: list[float], facet_id: UUID = FACET_A) -> CommunityAggregate:
    aggregator = StreamingAggregator()
    aggregate = _aggregate()
    for offset, value in enumerate(values):
        aggregate = aggregator.fold(
            _contribution({facet_id: value}), aggregate, NOW + timedelta(seconds=offset)
        )
    return aggregate


# ── Running statistics ────────────────────────────────────────────────────────


def test_first_contribution_seeds_the_statistics() -> None:
    aggregate = _fold_all([4.0])
    stat = aggregate.facet_stats[FACET_A]
    assert stat.mean == 4.0
    # Population variance, so a single observation is 0.0 rather than undefined.
    assert stat.variance == 0.0
    assert stat.n == 1
    assert aggregate.cohort_size == 1


def test_cohort_size_counts_every_folded_contribution() -> None:
    assert _fold_all([1.0, 2.0, 3.0, 4.0]).cohort_size == 4


def test_last_updated_at_tracks_the_most_recent_fold() -> None:
    aggregate = _fold_all([1.0, 2.0, 3.0])
    assert aggregate.last_updated_at == NOW + timedelta(seconds=2)


@given(
    values=st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=60,
    )
)
@settings(max_examples=200)
def test_incremental_mean_and_variance_match_a_batch_computation(values: list[float]) -> None:
    """Property: folding one at a time equals computing over the whole set.

    This is the guarantee that makes "no stored raw contributions" affordable.
    If it does not hold, the architecture's central trade is not being paid for.
    """
    aggregate = _fold_all(values)
    stat = aggregate.facet_stats[FACET_A]

    assert stat.n == len(values)
    assert stat.mean == pytest.approx(statistics.fmean(values), rel=1e-9, abs=1e-9)
    expected_variance = statistics.pvariance(values)
    assert stat.variance == pytest.approx(expected_variance, rel=1e-6, abs=1e-6)


@given(
    values=st.lists(
        st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=40,
    )
)
def test_variance_is_never_negative(values: list[float]) -> None:
    """Floating-point cancellation must not produce a negative variance."""
    stat = _fold_all(values).facet_stats[FACET_A]
    assert stat.variance >= 0.0
    assert math.isfinite(stat.variance)


@given(
    values=st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=30,
    )
)
def test_identical_observations_have_zero_variance(values: list[float]) -> None:
    repeated = [values[0]] * len(values)
    stat = _fold_all(repeated).facet_stats[FACET_A]
    assert stat.mean == pytest.approx(values[0], rel=1e-9, abs=1e-9)
    assert stat.variance == pytest.approx(0.0, abs=1e-6)


def test_facets_accumulate_independently() -> None:
    aggregator = StreamingAggregator()
    aggregate = _aggregate()
    aggregate = aggregator.fold(_contribution({FACET_A: 2.0, FACET_B: 10.0}), aggregate, NOW)
    aggregate = aggregator.fold(_contribution({FACET_A: 4.0}), aggregate, NOW)

    assert aggregate.facet_stats[FACET_A].n == 2
    assert aggregate.facet_stats[FACET_A].mean == pytest.approx(3.0)
    # A facet nobody rated the second time does not get a phantom observation.
    assert aggregate.facet_stats[FACET_B].n == 1
    assert aggregate.facet_stats[FACET_B].mean == pytest.approx(10.0)
    # cohort_size counts contributions, not facet observations.
    assert aggregate.cohort_size == 2


def test_a_contribution_with_no_scores_still_counts_toward_the_cohort() -> None:
    aggregate = StreamingAggregator().fold(_contribution({}), _aggregate(), NOW)
    assert aggregate.cohort_size == 1
    assert aggregate.facet_stats == {}


# ── The input aggregate is not mutated ────────────────────────────────────────


def test_fold_returns_a_new_aggregate_and_leaves_the_input_untouched() -> None:
    original = _aggregate()
    folded = StreamingAggregator().fold(_contribution({FACET_A: 5.0}), original, NOW)

    assert folded is not original
    assert original.cohort_size == 0
    assert original.facet_stats == {}


# ── Failure modes ─────────────────────────────────────────────────────────────


def test_double_fold_is_refused() -> None:
    aggregator = StreamingAggregator()
    contribution = _contribution({FACET_A: 3.0})
    aggregator.fold(contribution, _aggregate(), NOW)

    with pytest.raises(AlreadyFoldedError):
        aggregator.fold(contribution, _aggregate(), NOW)


def test_a_contribution_purged_by_a_failed_fold_cannot_be_folded_again() -> None:
    """A failed fold leaves an empty husk; folding it would be a phantom member."""
    aggregator = StreamingAggregator()
    contribution = _contribution({FACET_A: 3.0}, community_id=uuid4())

    with pytest.raises(MismatchedAggregateError):
        aggregator.fold(contribution, _aggregate(), NOW)

    assert is_purged(contribution)
    with pytest.raises(AlreadyFoldedError):
        aggregator.fold(contribution, _aggregate(), NOW)


def test_mismatched_community_is_refused() -> None:
    with pytest.raises(MismatchedAggregateError, match="community"):
        StreamingAggregator().fold(
            _contribution({FACET_A: 1.0}, community_id=uuid4()), _aggregate(), NOW
        )


def test_mismatched_place_is_refused() -> None:
    with pytest.raises(MismatchedAggregateError, match="place"):
        StreamingAggregator().fold(
            _contribution({FACET_A: 1.0}, place_id="somewhere-else"), _aggregate(), NOW
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_scores_are_refused(value: float) -> None:
    """A NaN would poison the running statistics with nothing to recompute from."""
    with pytest.raises(InvalidScoreError):
        StreamingAggregator().fold(_contribution({FACET_A: value}), _aggregate(), NOW)


def test_a_rejected_contribution_does_not_change_the_aggregate() -> None:
    aggregate = _aggregate()
    with pytest.raises(InvalidScoreError):
        StreamingAggregator().fold(
            _contribution({FACET_A: 1.0, FACET_B: float("nan")}), aggregate, NOW
        )
    # Scores are validated before any statistic is touched, so a partially
    # valid contribution folds nothing at all.
    assert aggregate.cohort_size == 0
    assert aggregate.facet_stats == {}


# ── Purging ───────────────────────────────────────────────────────────────────


def test_purge_is_idempotent() -> None:
    contribution = _contribution({FACET_A: 1.0}, free_text="something")
    purge(contribution)
    purge(contribution)
    assert is_purged(contribution)
    assert contribution.user_id == NIL_UUID


def test_purge_leaves_no_correlatable_user_identifier() -> None:
    """Every purged contribution ends up with the same tombstone, not a unique one."""
    first = _contribution({FACET_A: 1.0})
    second = _contribution({FACET_A: 2.0})
    purge(first)
    purge(second)
    assert first.user_id == second.user_id == NIL_UUID


@given(
    values=st.lists(
        st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=20,
    )
)
def test_every_folded_contribution_ends_up_purged(values: list[float]) -> None:
    assume(values)
    aggregator = StreamingAggregator()
    aggregate = _aggregate()
    contributions = [_contribution({FACET_A: value}) for value in values]
    for contribution in contributions:
        aggregate = aggregator.fold(contribution, aggregate, NOW)

    assert all(is_purged(contribution) for contribution in contributions)
    assert aggregate.cohort_size == len(values)


def test_folded_at_is_stamped_on_success_only() -> None:
    aggregator = StreamingAggregator()
    ok = _contribution({FACET_A: 1.0})
    aggregator.fold(ok, _aggregate(), NOW)
    assert ok.folded_at == NOW

    rejected = _contribution({FACET_A: float("nan")})
    with pytest.raises(InvalidScoreError):
        aggregator.fold(rejected, _aggregate(), NOW)
    assert rejected.folded_at is None


def test_the_aggregator_logs_at_debug_only(caplog: pytest.LogCaptureFixture) -> None:
    """Fold traffic is debug-level; nothing routine reaches INFO and above."""
    with caplog.at_level(logging.INFO, logger="app.services.aggregation"):
        StreamingAggregator().fold(_contribution({FACET_A: 1.0}), _aggregate(), NOW)
    assert caplog.records == []
