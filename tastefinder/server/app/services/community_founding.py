"""
app/services/community_founding.py
-----------------------------------
Deciding whether a community may be founded, and folding the founding batch.

`docs/03_API_CONTRACT.md`, "Founding a community": one person founds a
community by contributing ratings for at least `FOUNDING_MINIMUM_VENUES`
distinct venues. This module is that decision plus the fold, at the same layer
as the rest of the services (`aggregation.py`, `privacy_gate.py`,
`consent.py`) -- pure domain logic, no database session, no route.

**Founding used to require five distinct people, and no longer does.** The
rule was meant to buy bot resistance and did not: five authorisations prove
five *accounts*, not five people, and one person with five accounts satisfied
every check. It cost a great deal -- four other people each had to install the
app and sign in before the community existed at all -- for a property it never
actually delivered. The effort filter survives the change: one person rating
five venues demonstrates a coherent taste at least as well as five people each
rating one.

What that leaves unguarded is written down rather than glossed. There is now
no point anywhere in the platform where multiple distinct humans are
structurally required, which makes `OPEN-6` (Sybil resistance) and `OPEN-7`
(`cohort_size` counts contributions, not contributors) load-bearing rather
than theoretical: alone, one actor can found a community and, with repeated
contributions, push a venue past its threshold.

**Atomicity, and what it does and does not protect.** A rejected founding
creates nothing: no community, no orphaned membership, no half-built
aggregate. What a rejection does *not* preserve is the founding contributions
themselves. `StreamingAggregator.fold` purges every contribution it touches,
on success and on failure alike, so a batch that fails partway through folding
has already scrubbed what it folded before failing. That is the cost Phase 3
accepted for a single contribution, extended to a batch, and it is why the
structural checks below run *before* anything is folded: the likely failure
modes -- too few venues, a facet the community does not rate -- cost nothing,
because they are caught while the batch is still just data.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import CommunityStatus, Confidence, ContributionSource, Tier
from app.domain.facet_catalogue import FacetCatalogue
from app.domain.models import (
    Community,
    CommunityAggregate,
    CommunityMembership,
    Facet,
    RawContribution,
)
from app.services.aggregation import StreamingAggregator
from app.services.privacy_gate import ABSOLUTE_MINIMUM_THRESHOLD

# How many distinct venues a founding must cover. A starting value, not a
# derived one -- see "Open parameters" under "Founding a community" in
# docs/03_API_CONTRACT.md. Deliberately *not* the same number as a community's
# own min_cohort_threshold (OPEN-1 in docs/04_PRIVACY_INVARIANTS.md): this
# governs what it takes to start a community, that governs what it takes to
# publish a single venue's rating.
FOUNDING_MINIMUM_VENUES = 5


class FoundingError(Exception):
    """Base class for a rejected founding.

    Messages must not name a specific user, contribution, or facet score --
    the rule `docs/03_API_CONTRACT.md` sets for error bodies, applied here so
    that whatever route eventually surfaces these is compliant by default
    rather than by remembering to sanitise.
    """


class InsufficientVenuesError(FoundingError):
    """The batch covers fewer than `FOUNDING_MINIMUM_VENUES` distinct venues.

    Distinct *venues*, not contributions: rating the same place five times is
    not knowing five places, and the bar exists to demonstrate a taste rather
    than to measure typing.
    """


class UnsafeThresholdError(FoundingError):
    """`min_cohort_threshold` was below the floor a cohort can safely have."""


class UnscoredFacetError(FoundingError):
    """A contribution scored a facet the community did not select."""


@dataclass(frozen=True)
class FoundingContribution:
    """One rating in a founding batch.

    Carries no `user_id`: every contribution in a founding comes from the
    founder, who is named once on the call rather than repeated on each entry.
    Carries no `community_id` either -- the community does not exist until
    founding succeeds -- and no source or confidence, because founding is
    definitionally direct and stated.
    """

    place_id: str
    # Keyed by *catalogue key*, not facet_id. Facet ids do not exist until
    # founding creates them, so a founding request cannot reference one --
    # founding is the moment keys become ids.
    facet_scores: dict[str, float]
    free_text: str | None = None


@dataclass(frozen=True)
class FoundingResult:
    """What a successful founding produced.

    Deliberately holds no contribution-shaped object. `CommunityMembership`
    carries a `user_id` because membership is a persisted fact
    (`docs/02_DOMAIN_MODEL.md`); `CommunityAggregate` carries none, by
    construction (INV-RAW-2).
    """

    community: Community
    facets: tuple[Facet, ...]
    memberships: tuple[CommunityMembership, ...]
    # Keyed by place_id: one aggregate per venue the batch touched.
    aggregates: dict[str, CommunityAggregate]


def found_community(
    slug: str,
    min_cohort_threshold: int,
    facet_keys: frozenset[str] | set[str],
    catalogue: FacetCatalogue,
    founder_id: UUID,
    contributions: Sequence[FoundingContribution],
    now: datetime,
) -> FoundingResult:
    """Validate a founding batch, then fold it. All-or-nothing.

    Args:
        slug: the community's identifier. Uniqueness is a database
            constraint, not something this function can see; a caller
            persisting the result handles the collision.
        min_cohort_threshold: per-community, no default (OPEN-1).
        facet_keys: which catalogue facets this community rates on. Selected,
            never authored -- see app/domain/facet_catalogue.py.
        catalogue: the platform's facet vocabulary.
        founder_id: the account founding the community. Whether it belongs to
            a distinct real person is OPEN-6, and is not settled here.
        contributions: the founding batch, scoring facets by catalogue key.
        now: the instant the founding is made at. One value for the whole
            batch, because the batch is one act.

    Raises:
        UnsafeThresholdError: the threshold is below the individual floor.
        InsufficientVenuesError: too few distinct venues.
        UnknownFacetKeyError: (from `facet_catalogue`) a selected key is not
            in the catalogue.
        UnscoredFacetError: a contribution scored a facet this community did
            not select.
        InvalidScoreError: (from `aggregation`) a facet score was not finite.
            By then some contributions have been folded and purged; nothing is
            returned, so no community comes into existence.
    """
    if min_cohort_threshold < ABSOLUTE_MINIMUM_THRESHOLD:
        raise UnsafeThresholdError(
            f"min_cohort_threshold must be at least {ABSOLUTE_MINIMUM_THRESHOLD}: "
            f"a smaller cohort is an individual, and publishing it breaches "
            f"INV-EXPOSE-1."
        )

    venues = {contribution.place_id for contribution in contributions}
    if len(venues) < FOUNDING_MINIMUM_VENUES:
        raise InsufficientVenuesError(
            f"Founding needs ratings for at least {FOUNDING_MINIMUM_VENUES} "
            f"distinct venues; this batch covered {len(venues)}."
        )

    definitions = catalogue.resolve(facet_keys)

    scored_keys = {key for c in contributions for key in c.facet_scores}
    unselected = scored_keys - {definition.key for definition in definitions}
    if unselected:
        raise UnscoredFacetError(
            f"{len(unselected)} facet(s) were scored that this community does "
            f"not rate on."
        )

    community = Community(
        slug=slug,
        min_cohort_threshold=min_cohort_threshold,
        status=CommunityStatus.SEEDING,
        created_at=now,
    )
    # SEEDING and LIVE describe scale only -- see the tier note in
    # docs/03_API_CONTRACT.md. A founding is one person now, so a new
    # community starts SEEDING and reaches LIVE once joiners arrive. The check
    # is kept rather than assumed away so that a deliberately low threshold
    # still behaves consistently.
    if community.can_go_live(current_cohort=1):
        community = community.model_copy(update={"status": CommunityStatus.LIVE})

    facets = tuple(
        Facet(
            community_id=community.community_id,
            name=definition.name,
            value_type=definition.value_type,
            scale_min=definition.scale_min,
            scale_max=definition.scale_max,
        )
        for definition in definitions
    )
    # The catalogue key a contribution scored, mapped to the facet id that
    # key just became. This mapping is what makes founding the moment keys
    # turn into ids.
    facet_id_by_key = {
        definition.key: facet.facet_id
        for definition, facet in zip(definitions, facets, strict=True)
    }

    memberships = (
        CommunityMembership(
            user_id=founder_id,
            community_id=community.community_id,
            tier=Tier.FOUNDER,
            joined_at=now,
        ),
    )

    aggregator = StreamingAggregator()
    aggregates: dict[str, CommunityAggregate] = {}
    for contribution in contributions:
        aggregate = aggregates.get(contribution.place_id) or CommunityAggregate(
            community_id=community.community_id,
            place_id=contribution.place_id,
            last_updated_at=now,
        )
        raw = RawContribution(
            user_id=founder_id,
            community_id=community.community_id,
            place_id=contribution.place_id,
            facet_scores={
                facet_id_by_key[key]: score
                for key, score in contribution.facet_scores.items()
            },
            free_text=contribution.free_text,
            source=ContributionSource.DIRECT,
            confidence=Confidence.STATED,
            captured_at=now,
        )
        aggregates[contribution.place_id] = aggregator.fold(raw, aggregate, now)

    return FoundingResult(
        community=community,
        facets=facets,
        memberships=memberships,
        aggregates=aggregates,
    )
