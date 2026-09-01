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

from app.domain.enums import CommunityStatus, FacetValueType, Tier
from app.domain.facet_catalogue import (
    FacetCatalogue,
    FacetDefinition,
    UnknownFacetKeyError,
)
from app.services.aggregation import InvalidScoreError
from app.services.community_founding import (
    FOUNDING_MINIMUM_VENUES,
    FoundingContribution,
    FoundingResult,
    InsufficientVenuesError,
    UnsafeThresholdError,
    UnscoredFacetError,
    found_community,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
FOUNDER = uuid4()

# The platform owns the vocabulary; a test owns this one. There is no default
# catalogue, deliberately -- see app/domain/facet_catalogue.py.
CATALOGUE = FacetCatalogue(
    definitions=(
        FacetDefinition(
            key="body",
            name="Body",
            value_type=FacetValueType.NUMERIC,
            scale_min=0.0,
            scale_max=10.0,
        ),
        FacetDefinition(
            key="finish",
            name="Finish",
            value_type=FacetValueType.NUMERIC,
            scale_min=0.0,
            scale_max=10.0,
        ),
    )
)
FACET_KEYS = frozenset({"body"})


def _facet_id(result: FoundingResult, key: str) -> UUID:
    """The id the catalogue key became for this community."""
    name = next(d.name for d in CATALOGUE.definitions if d.key == key)
    return next(facet.facet_id for facet in result.facets if facet.name == name)


def _contribution(
    place_id: str, score: float = 4.0, free_text: str | None = None
) -> FoundingContribution:
    return FoundingContribution(
        place_id=place_id, facet_scores={"body": score}, free_text=free_text
    )


def _valid_batch(venues: int = FOUNDING_MINIMUM_VENUES) -> list[FoundingContribution]:
    return [_contribution(f"place-{index}") for index in range(venues)]


def _found(
    batch: list[FoundingContribution],
    slug: str = "wine",
    threshold: int = 10,
    keys: frozenset[str] = FACET_KEYS,
) -> FoundingResult:
    return found_community(slug, threshold, keys, CATALOGUE, FOUNDER, batch, NOW)


# ── The happy path ────────────────────────────────────────────────────────────


def test_a_valid_batch_founds_a_community() -> None:
    result = _found(_valid_batch())

    assert result.community.slug == "wine"
    assert result.community.min_cohort_threshold == 10
    assert result.community.created_at == NOW


def test_the_founder_becomes_the_sole_founder_tier_member() -> None:
    result = _found(_valid_batch())

    assert len(result.memberships) == 1
    membership = result.memberships[0]
    assert membership.user_id == FOUNDER
    assert membership.tier is Tier.FOUNDER
    assert membership.community_id == result.community.community_id


def test_one_aggregate_per_venue_all_pointing_at_the_new_community() -> None:
    result = _found(_valid_batch())

    assert set(result.aggregates) == {
        f"place-{i}" for i in range(FOUNDING_MINIMUM_VENUES)
    }
    assert all(
        aggregate.community_id == result.community.community_id
        for aggregate in result.aggregates.values()
    )
    # The founder rated each venue once, so each aggregate holds exactly one.
    assert all(aggregate.cohort_size == 1 for aggregate in result.aggregates.values())


def test_rating_one_venue_more_than_once_accumulates_on_that_venue() -> None:
    """Permitted, and exactly the shape OPEN-7 warns about: cohort_size counts
    contributions, so one person can raise it without help."""
    batch = _valid_batch()
    batch += [_contribution("place-0", score=float(n)) for n in range(3)]

    result = _found(batch)

    assert result.aggregates["place-0"].cohort_size == 4
    assert result.aggregates["place-0"].facet_stats[_facet_id(result, "body")].n == 4


def test_more_venues_than_the_minimum_is_allowed() -> None:
    result = _found(_valid_batch(venues=9))
    assert len(result.aggregates) == 9


# ── Status is about scale, not tier ───────────────────────────────────────────


def test_a_new_community_starts_seeding() -> None:
    result = _found(_valid_batch(), threshold=10)
    assert result.community.status is CommunityStatus.SEEDING


def test_a_founding_of_one_does_not_clear_even_the_lowest_legal_threshold() -> None:
    """One founder is a cohort of one, and the floor is two (INV-EXPOSE-1)."""
    result = _found(_valid_batch(), threshold=2)
    assert result.community.status is CommunityStatus.SEEDING


# ── The bar ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("venues", [0, 1, 4])
def test_too_few_distinct_venues_is_refused(venues: int) -> None:
    with pytest.raises(InsufficientVenuesError):
        _found(_valid_batch(venues=venues))


def test_rating_one_venue_five_times_is_not_five_venues() -> None:
    """The bar counts distinct places, not contributions."""
    batch = [_contribution("the-only-place", score=float(n)) for n in range(5)]

    with pytest.raises(InsufficientVenuesError):
        _found(batch)


def test_exactly_the_minimum_is_enough() -> None:
    result = _found(_valid_batch(venues=FOUNDING_MINIMUM_VENUES))
    assert len(result.aggregates) == FOUNDING_MINIMUM_VENUES


@pytest.mark.parametrize("threshold", [-1, 0, 1])
def test_a_threshold_below_the_individual_floor_is_refused(threshold: int) -> None:
    """A cohort of one is an individual (INV-EXPOSE-1)."""
    with pytest.raises(UnsafeThresholdError):
        _found(_valid_batch(), threshold=threshold)


# ── Nothing half-founded ──────────────────────────────────────────────────────


def test_a_structurally_invalid_batch_is_rejected_before_anything_is_folded() -> None:
    """The likely failure costs nothing: the batch is still intact afterwards."""
    batch = _valid_batch(venues=3)

    with pytest.raises(InsufficientVenuesError):
        _found(batch)

    # FoundingContribution is frozen and never reaches the aggregator on this
    # path, so the caller's data is untouched and the attempt can be retried.
    assert all(contribution.facet_scores for contribution in batch)


def test_a_non_finite_score_produces_no_community() -> None:
    batch = _valid_batch()
    batch.append(_contribution("place-0", score=float("nan")))

    with pytest.raises(InvalidScoreError):
        _found(batch)


def test_the_result_carries_no_contribution_shaped_object() -> None:
    """Only membership may carry a user_id; aggregates never do (INV-RAW-2)."""
    result = _found(_valid_batch())

    for aggregate in result.aggregates.values():
        dumped = aggregate.model_dump()
        assert "user_id" not in dumped
        assert "free_text" not in dumped
        assert "facet_scores" not in dumped


def test_free_text_never_reaches_the_aggregates() -> None:
    batch = _valid_batch()
    batch[0] = _contribution(batch[0].place_id, free_text="ZZQX-distinctive-marker")

    result = _found(batch)

    assert "ZZQX-distinctive-marker" not in str(result.aggregates)
    assert "ZZQX-distinctive-marker" not in str(result.community)


# ── The platform owns the vocabulary ──────────────────────────────────────────


def test_founding_creates_a_facet_per_selected_key() -> None:
    result = _found(_valid_batch(), keys=frozenset({"body", "finish"}))

    assert {facet.name for facet in result.facets} == {"Body", "Finish"}
    assert all(f.community_id == result.community.community_id for f in result.facets)


def test_facet_names_come_from_the_catalogue_not_the_request() -> None:
    """A founder selects; they cannot author a name."""
    result = _found(_valid_batch())

    assert [facet.name for facet in result.facets] == ["Body"]


def test_a_key_outside_the_catalogue_is_refused() -> None:
    with pytest.raises(UnknownFacetKeyError):
        _found(_valid_batch(), keys=frozenset({"invented"}))


def test_scoring_a_facet_the_community_did_not_select_is_refused() -> None:
    batch = _valid_batch()
    batch[0] = FoundingContribution(
        place_id=batch[0].place_id, facet_scores={"finish": 4.0}
    )

    with pytest.raises(UnscoredFacetError):
        _found(batch)
