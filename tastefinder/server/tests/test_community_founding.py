"""
tests/test_community_founding.py
---------------------------------
Founding a community: the bar, and what a successful founding produces.

The privacy properties here are inherited rather than new -- founding folds
through the same `StreamingAggregator` as any other contribution, so
INV-RAW-1/2/3 are already covered by tests/test_privacy_invariants.py. What is
tested here is the part that is genuinely new and easy to get wrong: the
composition rules for a founding batch, and the fact that a rejected founding
produces nothing at all.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.enums import CommunityStatus, Tier
from app.services.aggregation import InvalidScoreError
from app.services.community_founding import (
    FOUNDING_MINIMUM_USERS,
    FoundingContribution,
    InsufficientDistinctVenuesError,
    InsufficientFoundersError,
    UnsafeThresholdError,
    found_community,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
FACET = uuid4()


def _contribution(
    user_id: UUID, place_id: str, score: float = 4.0, free_text: str | None = None
) -> FoundingContribution:
    return FoundingContribution(
        user_id=user_id,
        place_id=place_id,
        facet_scores={FACET: score},
        free_text=free_text,
    )


def _valid_batch(count: int = FOUNDING_MINIMUM_USERS) -> list[FoundingContribution]:
    """`count` founders, each introducing one venue nobody else rated."""
    return [_contribution(uuid4(), f"place-{index}") for index in range(count)]


# ── The happy path ────────────────────────────────────────────────────────────


def test_a_valid_batch_founds_a_community() -> None:
    batch = _valid_batch()
    result = found_community("wine", 10, batch, NOW)

    assert result.community.slug == "wine"
    assert result.community.min_cohort_threshold == 10
    assert result.community.created_at == NOW


def test_every_founder_becomes_a_founder_tier_member() -> None:
    batch = _valid_batch()
    result = found_community("wine", 10, batch, NOW)

    assert len(result.memberships) == FOUNDING_MINIMUM_USERS
    assert {m.user_id for m in result.memberships} == {c.user_id for c in batch}
    assert all(m.tier is Tier.FOUNDER for m in result.memberships)
    assert all(m.community_id == result.community.community_id for m in result.memberships)


def test_one_aggregate_per_venue_all_pointing_at_the_new_community() -> None:
    result = found_community("wine", 10, _valid_batch(), NOW)

    assert set(result.aggregates) == {f"place-{i}" for i in range(FOUNDING_MINIMUM_USERS)}
    assert all(
        aggregate.community_id == result.community.community_id
        for aggregate in result.aggregates.values()
    )
    # One founder rated each venue, so each aggregate holds exactly one.
    assert all(aggregate.cohort_size == 1 for aggregate in result.aggregates.values())


def test_a_venue_several_founders_rated_accumulates_all_of_them() -> None:
    batch = _valid_batch()
    shared = "place-shared"
    batch += [_contribution(batch[i].user_id, shared, score=float(i)) for i in range(3)]

    result = found_community("wine", 10, batch, NOW)

    assert result.aggregates[shared].cohort_size == 3
    assert result.aggregates[shared].facet_stats[FACET].n == 3
    assert result.aggregates[shared].facet_stats[FACET].mean == pytest.approx(1.0)


def test_more_founders_than_the_minimum_is_allowed() -> None:
    result = found_community("wine", 10, _valid_batch(count=8), NOW)
    assert len(result.memberships) == 8


# ── Status is about scale, not tier ───────────────────────────────────────────


def test_a_founding_group_below_its_own_threshold_starts_seeding() -> None:
    result = found_community("wine", 10, _valid_batch(), NOW)
    assert result.community.status is CommunityStatus.SEEDING


def test_a_founding_group_that_clears_its_own_threshold_starts_live() -> None:
    result = found_community("wine", ABSOLUTE_MIN := 5, _valid_batch(), NOW)
    assert ABSOLUTE_MIN == FOUNDING_MINIMUM_USERS
    assert result.community.status is CommunityStatus.LIVE


# ── The bar ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("count", [0, 1, 4])
def test_too_few_distinct_founders_is_refused(count: int) -> None:
    with pytest.raises(InsufficientFoundersError):
        found_community("wine", 10, _valid_batch(count=count), NOW)


def test_one_person_submitting_five_venues_is_not_five_founders() -> None:
    """The bar counts distinct people, not contributions."""
    solo = uuid4()
    batch = [_contribution(solo, f"place-{index}") for index in range(5)]

    with pytest.raises(InsufficientFoundersError):
        found_community("wine", 10, batch, NOW)


def test_a_founder_who_brought_no_new_venue_is_refused() -> None:
    """Six founders sharing five venues: someone cannot be credited."""
    batch = _valid_batch()
    freeloader = uuid4()
    batch += [_contribution(freeloader, "place-0"), _contribution(freeloader, "place-1")]

    with pytest.raises(InsufficientDistinctVenuesError):
        found_community("wine", 10, batch, NOW)


def test_a_founder_may_also_rate_a_venue_someone_else_rated() -> None:
    batch = _valid_batch()
    batch.append(_contribution(batch[0].user_id, "place-shared"))
    batch.append(_contribution(batch[1].user_id, "place-shared"))

    result = found_community("wine", 10, batch, NOW)

    assert len(result.memberships) == FOUNDING_MINIMUM_USERS
    assert result.aggregates["place-shared"].cohort_size == 2


def test_agreeing_with_another_founders_only_venue_does_not_refuse_the_founding() -> None:
    """The reason the rule is a matching and not an exclusivity test.

    place-1 is founder 1's only venue, and founder 0 rates it too. Under an
    exclusivity reading founder 1 would lose their claim and the whole
    founding would be refused for an act of agreement. Under the matching
    reading founder 0 is credited with place-0 and founder 1 keeps place-1.
    """
    batch = _valid_batch()
    batch.append(_contribution(batch[0].user_id, "place-1"))

    result = found_community("wine", 10, batch, NOW)

    assert len(result.memberships) == FOUNDING_MINIMUM_USERS
    assert result.aggregates["place-1"].cohort_size == 2


def test_five_founders_who_all_rated_the_same_five_venues_can_be_credited() -> None:
    """Total overlap is fine: an assignment still exists."""
    founders = [uuid4() for _ in range(5)]
    batch = [
        _contribution(founder, f"place-{index}")
        for founder in founders
        for index in range(5)
    ]

    result = found_community("wine", 10, batch, NOW)

    assert len(result.memberships) == 5
    assert len(result.aggregates) == 5
    assert all(aggregate.cohort_size == 5 for aggregate in result.aggregates.values())


def test_five_founders_all_rating_the_same_single_venue_is_refused() -> None:
    """Five people and one venue cannot be five distinct credits."""
    batch = [_contribution(uuid4(), "the-only-place") for _ in range(5)]

    with pytest.raises(InsufficientDistinctVenuesError):
        found_community("wine", 10, batch, NOW)


def test_a_successful_founding_always_covers_at_least_one_venue_per_founder() -> None:
    """The outcome the bar exists for, whichever reading produced it."""
    batch = _valid_batch(count=7)
    batch.append(_contribution(batch[0].user_id, "place-1"))

    result = found_community("wine", 10, batch, NOW)

    assert len(result.aggregates) >= len(result.memberships)


@pytest.mark.parametrize("threshold", [-1, 0, 1])
def test_a_threshold_below_the_individual_floor_is_refused(threshold: int) -> None:
    """A cohort of one is an individual (INV-EXPOSE-1)."""
    with pytest.raises(UnsafeThresholdError):
        found_community("wine", threshold, _valid_batch(), NOW)


# ── Nothing half-founded ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("batch_factory", "expected"),
    [
        (lambda: _valid_batch(count=3), InsufficientFoundersError),
        (
            lambda: [_contribution(uuid4(), "same") for _ in range(5)],
            InsufficientDistinctVenuesError,
        ),
    ],
)
def test_a_structurally_invalid_batch_is_rejected_before_anything_is_folded(
    batch_factory: object, expected: type[Exception]
) -> None:
    """The likely failures cost nothing: the batch is still intact afterwards."""
    batch = batch_factory()  # type: ignore[operator]

    with pytest.raises(expected):
        found_community("wine", 10, batch, NOW)

    # FoundingContribution is frozen and never handed to the aggregator on
    # these paths, so the caller's data is untouched and the attempt can be
    # corrected and retried.
    assert all(contribution.facet_scores for contribution in batch)


def test_a_non_finite_score_produces_no_community() -> None:
    batch = _valid_batch()
    batch.append(_contribution(batch[0].user_id, "place-0", score=float("nan")))

    with pytest.raises(InvalidScoreError):
        found_community("wine", 10, batch, NOW)


def test_the_result_carries_no_contribution_shaped_object() -> None:
    """Only membership may carry a user_id; aggregates never do (INV-RAW-2)."""
    result = found_community("wine", 10, _valid_batch(), NOW)

    for aggregate in result.aggregates.values():
        dumped = aggregate.model_dump()
        assert "user_id" not in dumped
        assert "free_text" not in dumped
        assert "facet_scores" not in dumped


def test_free_text_never_reaches_the_aggregates() -> None:
    batch = _valid_batch()
    batch[0] = _contribution(
        batch[0].user_id, batch[0].place_id, free_text="ZZQX-distinctive-marker"
    )

    result = found_community("wine", 10, batch, NOW)

    assert "ZZQX-distinctive-marker" not in str(result.aggregates)
    assert "ZZQX-distinctive-marker" not in str(result.community)
