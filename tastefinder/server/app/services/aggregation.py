"""
app/services/aggregation.py
---------------------------
Incremental folding of a `RawContribution` into a `CommunityAggregate`.

Two properties define this module, and both come from
`docs/04_PRIVACY_INVARIANTS.md` rather than from performance concerns:

1. **Aggregation is incremental, never a recompute.** There are no stored raw
   contributions to recompute from -- see the "RawContribution persistence"
   decision in `docs/02_DOMAIN_MODEL.md`. Running statistics are updated in
   place with Welford's algorithm.
2. **Identified data does not survive the call.** `fold` purges the
   contribution in a `finally` block, so a contribution is scrubbed whether the
   fold succeeded or raised (INV-RAW-1). This is deliberate and it costs
   something: a rejected contribution cannot be corrected and resubmitted from
   the object that was passed in. `CLAUDE.md` makes transience the rule that
   overrides everything else, and a failed fold holding identified data in
   memory for an unbounded time is exactly what it forbids.

Nothing here logs a payload. Log lines and exception messages carry aggregate,
community, place and contribution identifiers only -- never `user_id`, never a
facet value, never free text (INV-RAW-4).
"""

import logging
import math
from datetime import datetime
from uuid import UUID

from app.domain.models import CommunityAggregate, FacetStat, RawContribution

logger = logging.getLogger(__name__)

# Tombstone written over `user_id` by `purge`. A nil UUID is a valid UUID, so
# the model stays constructible, but it points at no user and is the same value
# for every purged contribution -- it cannot be correlated back to anybody.
NIL_UUID = UUID(int=0)


class AggregationError(Exception):
    """Base class for fold failures.

    Subclasses must keep payload data out of their messages: an exception
    string reaches logs and error trackers, which is exactly the leak
    INV-RAW-4 forbids.
    """


class AlreadyFoldedError(AggregationError):
    """A contribution was submitted for folding twice.

    `folded_at` exists on the in-memory model for precisely this check -- see
    `docs/02_DOMAIN_MODEL.md`. A double fold would inflate `cohort_size` and
    skew every facet statistic, with no raw record to recompute from.
    """


class MismatchedAggregateError(AggregationError):
    """The contribution and the aggregate describe different slices."""


class InvalidScoreError(AggregationError):
    """A facet score was not a finite number.

    Rejected rather than folded because a NaN or infinity poisons the running
    mean and variance permanently: with no stored raw contributions, there is
    nothing to recompute the aggregate from once it is corrupt.
    """


def purge(contribution: RawContribution) -> None:
    """Scrub the identified fields of a contribution, in place.

    Overwrites rather than relying on the object being dropped: the caller
    holds the reference it passed in, and "it will be garbage collected
    eventually" is not the guarantee INV-RAW-1 asks for.

    Idempotent, so it is safe in a `finally` block that may run after a partial
    fold.
    """
    contribution.facet_scores = {}
    contribution.free_text = None
    contribution.user_id = NIL_UUID
    contribution.source_job_id = None


def is_purged(contribution: RawContribution) -> bool:
    """Whether every identified field has been scrubbed."""
    return (
        contribution.user_id == NIL_UUID
        and not contribution.facet_scores
        and contribution.free_text is None
        and contribution.source_job_id is None
    )


def _fold_score(facet_id: UUID, stat: FacetStat | None, value: float) -> FacetStat:
    """Add one observation to a facet's running statistics.

    Welford's online algorithm, carrying the sum of squared deviations as
    `variance * n` because `FacetStat` stores variance rather than M2.

    `variance` is the *population* variance of the folded observations, not the
    sample variance: at `n == 1` the sample variance is undefined, and the one
    thing this function must never do is return a value that cannot be folded
    into again.

    Note the numerical cost of the shape: reconstructing M2 from a rounded
    `variance` loses a little precision on every fold, where keeping M2
    directly would not. `FacetStat` is an explicit placeholder pending OPEN-3
    (`docs/02_DOMAIN_MODEL.md`), so the field set is not ours to change here;
    if the mechanism chosen there keeps mean/variance/n, carrying M2 instead of
    variance is the first thing to revisit.
    """
    if stat is None:
        return FacetStat(facet_id=facet_id, mean=value, variance=0.0, n=1)

    n = stat.n + 1
    delta = value - stat.mean
    mean = stat.mean + delta / n
    m2 = stat.variance * stat.n + delta * (value - mean)
    # Squared deviations cannot be negative; floating-point cancellation can
    # still produce a tiny negative, which would surface as a NaN standard
    # deviation downstream.
    return FacetStat(facet_id=facet_id, mean=mean, variance=max(m2 / n, 0.0), n=n)


class StreamingAggregator:
    """Folds contributions into a running aggregate, one at a time.

    Holds no state of its own. It is a class rather than a function because
    `docs/00_BOOTSTRAP.md` names it as the seam that later phases (batched
    updates for OPEN-2, a different statistic for OPEN-3) will replace.
    """

    def fold(
        self,
        contribution: RawContribution,
        aggregate: CommunityAggregate,
        now: datetime,
    ) -> CommunityAggregate:
        """Fold one contribution into `aggregate` and purge the contribution.

        Returns a new `CommunityAggregate`; the input aggregate is not mutated,
        so a failed fold cannot leave a half-updated aggregate behind.

        The contribution is purged on every path out of this method, including
        the error paths -- see the module docstring for why.

        Raises:
            AlreadyFoldedError: the contribution has been folded or purged before.
            MismatchedAggregateError: community or place do not match.
            InvalidScoreError: a facet score is not finite.
        """
        try:
            if contribution.folded_at is not None or is_purged(contribution):
                # Both conditions matter. `folded_at` catches a genuine double
                # fold; `is_purged` catches the object left behind by a fold
                # that raised, which has empty scores and would otherwise be
                # folded as a phantom contributor -- inflating cohort_size
                # while adding no data.
                raise AlreadyFoldedError(
                    f"Contribution {contribution.contribution_id} has already been consumed."
                )
            if contribution.community_id != aggregate.community_id:
                raise MismatchedAggregateError(
                    f"Contribution community {contribution.community_id} does not match "
                    f"aggregate community {aggregate.community_id}."
                )
            if contribution.place_id != aggregate.place_id:
                raise MismatchedAggregateError(
                    f"Contribution place {contribution.place_id} does not match "
                    f"aggregate place {aggregate.place_id}."
                )

            for facet_id, value in contribution.facet_scores.items():
                if not math.isfinite(value):
                    # The offending value is deliberately absent from the
                    # message: it is rating data (INV-RAW-4).
                    raise InvalidScoreError(
                        f"Facet {facet_id} carried a non-finite score on contribution "
                        f"{contribution.contribution_id}."
                    )

            facet_stats = dict(aggregate.facet_stats)
            for facet_id, value in contribution.facet_scores.items():
                facet_stats[facet_id] = _fold_score(facet_id, facet_stats.get(facet_id), value)

            folded = aggregate.model_copy(
                update={
                    "facet_stats": facet_stats,
                    # Counts contributions, not distinct contributors. See
                    # OPEN-7 in docs/04_PRIVACY_INVARIANTS.md: de-duplicating
                    # by user would require the user-indexed structure that
                    # INV-RAW-2 forbids.
                    "cohort_size": aggregate.cohort_size + 1,
                    "last_updated_at": now,
                }
            )
            contribution.folded_at = now
            logger.debug(
                "Folded a contribution into aggregate %s (%d facets, cohort now %d).",
                aggregate.aggregate_id,
                len(contribution.facet_scores),
                folded.cohort_size,
            )
            return folded
        finally:
            purge(contribution)
