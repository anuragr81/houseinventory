"""
app/services/community_founding.py
-----------------------------------
Deciding whether a community may be founded, and folding the founding batch.

`docs/03_API_CONTRACT.md`, "Founding a community": one request carries
contributions from five distinct users, each introducing at least one venue no
other member of the group introduced. This module is that decision plus the
fold, at the same layer as the rest of the services (`aggregation.py`,
`privacy_gate.py`, `consent.py`) -- pure domain logic, no database session, no
route.

A route needs a way to know that five authorisations really do belong to five
distinct users, and that is an authentication design which does not exist yet
(`docs/00_BOOTSTRAP.md`'s exclusion list). This module takes that as already
established and receives plain `user_id`s, the same way
`consent.authorise_google_import` takes `age_verified_adult` as a parameter
rather than solving age verification itself.

**Atomicity, and what it does and does not protect.** A rejected founding
creates nothing: no community, no orphaned membership, no half-built
aggregate. What a rejection does *not* preserve is the founding contributions
themselves. `StreamingAggregator.fold` purges every contribution it touches,
on success and on failure alike, so a batch that fails partway through folding
has already scrubbed what it folded before failing. That is the cost Phase 3
accepted for a single contribution, extended to a batch, and it is why the
structural checks below run *before* anything is folded: the failure modes
that are actually likely -- too few founders, a founder with no venue of their
own -- cost nothing, because they are caught while the batch is still just
data.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import CommunityStatus, Confidence, ContributionSource, Tier
from app.domain.models import (
    Community,
    CommunityAggregate,
    CommunityMembership,
    RawContribution,
)
from app.services.aggregation import StreamingAggregator
from app.services.privacy_gate import ABSOLUTE_MINIMUM_THRESHOLD

# A starting value, not a derived one -- see "Open parameters" under "Founding
# a community" in docs/03_API_CONTRACT.md. Deliberately *not* the same number
# as a community's own min_cohort_threshold (OPEN-1 in
# docs/04_PRIVACY_INVARIANTS.md): this governs what it takes to start a
# community, that governs what it takes to publish a single venue's rating.
FOUNDING_MINIMUM_USERS = 5


class FoundingError(Exception):
    """Base class for a rejected founding.

    Messages must not name a specific user, contribution, or facet score --
    the rule `docs/03_API_CONTRACT.md` sets for error bodies, applied here so
    that whatever route eventually surfaces these is compliant by default
    rather than by remembering to sanitise.
    """


class InsufficientFoundersError(FoundingError):
    """Fewer than `FOUNDING_MINIMUM_USERS` distinct users in the batch."""


class InsufficientDistinctVenuesError(FoundingError):
    """The group cannot be credited with one distinct venue each.

    The rule is a matching, not an exclusivity test: founding succeeds when
    every founder can be *assigned* a venue they rated, with no two founders
    assigned the same one. Overlap is fine -- five founders who all rated the
    same five venues satisfy this, because an assignment exists.

    An exclusivity test was the obvious first reading, and it is wrong in a
    way worth recording. Within one atomic batch there is no ordering, so
    "the venue X introduced" can only mean "the venue only X rated" -- which
    means a founder agreeing with another founder's single venue would strip
    that founder of their claim and refuse the whole founding. Agreement
    between founders is the last thing this bar should punish.

    Either way the outcome the bar exists for holds: a successful founding
    covers at least as many distinct venues as it has founders. And either way
    the check is scoped to this batch, so the association between a founder and
    the venue credited to them lives only for the length of this call and is
    never written down.
    """


class UnsafeThresholdError(FoundingError):
    """`min_cohort_threshold` was below the floor a cohort can safely have."""


@dataclass(frozen=True)
class FoundingContribution:
    """One founder's rating, as the caller has already authorised it.

    Carries no `community_id`: the community does not exist until founding
    succeeds. Carries no source or confidence either -- founding is
    definitionally direct and stated, so the caller does not get to say
    otherwise.
    """

    user_id: UUID
    place_id: str
    facet_scores: dict[UUID, float]
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
    memberships: tuple[CommunityMembership, ...]
    # Keyed by place_id: one aggregate per venue the batch touched.
    aggregates: dict[str, CommunityAggregate]


def _distinct_users(contributions: Sequence[FoundingContribution]) -> set[UUID]:
    return {contribution.user_id for contribution in contributions}


def _credit_one_venue_each(
    contributions: Sequence[FoundingContribution],
) -> dict[str, UUID]:
    """Assign each founder a distinct venue they rated, as far as possible.

    Kuhn's algorithm for maximum bipartite matching -- founders on one side,
    the venues they rated on the other. Returns the assignment it found, keyed
    by `place_id`; the caller compares its size against the number of founders
    to see whether everyone could be credited.

    Iteration order is sorted rather than incidental so the same batch always
    produces the same assignment, which keeps failures reproducible.

    Recursion depth is bounded by the number of founders. A founding batch is
    a handful of people by construction, and capping request size belongs to
    whatever route eventually accepts one, not here.
    """
    venues_by_founder: dict[UUID, set[str]] = {}
    for contribution in contributions:
        venues_by_founder.setdefault(contribution.user_id, set()).add(
            contribution.place_id
        )

    credited: dict[str, UUID] = {}

    def _assign(founder: UUID, tried: set[str]) -> bool:
        for venue in sorted(venues_by_founder[founder]):
            if venue in tried:
                continue
            tried.add(venue)
            incumbent = credited.get(venue)
            if incumbent is None or _assign(incumbent, tried):
                credited[venue] = founder
                return True
        return False

    for founder in sorted(venues_by_founder):
        _assign(founder, set())
    return credited


def found_community(
    slug: str,
    min_cohort_threshold: int,
    contributions: Sequence[FoundingContribution],
    now: datetime,
) -> FoundingResult:
    """Validate a founding batch, then fold it. All-or-nothing.

    Args:
        slug: the community's identifier. Uniqueness is a database
            constraint, not something this function can see; a caller
            persisting the result handles the collision.
        min_cohort_threshold: per-community, no default (OPEN-1).
        contributions: the founding batch, already authorised, with
            `user_id`s the caller has established are distinct people's
            accounts.
        now: the instant the founding is made at. One value for the whole
            batch, because the batch is one act.

    Raises:
        UnsafeThresholdError: the threshold is below the individual floor.
        InsufficientFoundersError: too few distinct contributors.
        InsufficientDistinctVenuesError: the founders cannot be credited with
            one distinct venue each.
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

    distinct_users = _distinct_users(contributions)
    if len(distinct_users) < FOUNDING_MINIMUM_USERS:
        raise InsufficientFoundersError(
            f"Founding needs contributions from at least {FOUNDING_MINIMUM_USERS} "
            f"distinct people; this batch had {len(distinct_users)}."
        )

    credited = _credit_one_venue_each(contributions)
    if len(credited) < len(distinct_users):
        raise InsufficientDistinctVenuesError(
            f"{len(distinct_users)} founders can be credited with only "
            f"{len(credited)} distinct venues between them; founding needs one "
            f"each."
        )

    community = Community(
        slug=slug,
        min_cohort_threshold=min_cohort_threshold,
        status=CommunityStatus.SEEDING,
        created_at=now,
    )
    # SEEDING and LIVE describe scale only -- see the tier note in
    # docs/03_API_CONTRACT.md. A founding group large enough to clear its own
    # threshold starts LIVE; a smaller one starts SEEDING and gets there when
    # joiners arrive.
    if community.can_go_live(len(distinct_users)):
        community = community.model_copy(update={"status": CommunityStatus.LIVE})

    memberships = tuple(
        CommunityMembership(
            user_id=user_id,
            community_id=community.community_id,
            tier=Tier.FOUNDER,
            joined_at=now,
        )
        for user_id in sorted(distinct_users)
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
            user_id=contribution.user_id,
            community_id=community.community_id,
            place_id=contribution.place_id,
            facet_scores=dict(contribution.facet_scores),
            free_text=contribution.free_text,
            source=ContributionSource.DIRECT,
            confidence=Confidence.STATED,
            captured_at=now,
        )
        aggregates[contribution.place_id] = aggregator.fold(raw, aggregate, now)

    return FoundingResult(
        community=community, memberships=memberships, aggregates=aggregates
    )
