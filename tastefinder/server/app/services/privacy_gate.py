"""
app/services/privacy_gate.py
----------------------------
The gate every aggregate read passes through.

`docs/04_PRIVACY_INVARIANTS.md` requires suppression on **every** read of
**every** slice (INV-EXPOSE-4), and that only `PublicAggregateView` leaves the
system (INV-EXPOSE-5). Those two together mean routes must not reach for
`CommunityAggregate.to_public_view` themselves: `public_view` below is the only
supported way out, and it takes the suppression decision before it projects.

`apply_noise` is an interface with no mechanism behind it, on purpose. Choosing
between threshold suppression and differential privacy, and choosing epsilon,
are OPEN-2 and OPEN-3 -- open decisions for the project owner. A guessed
epsilon is worse than none, because it produces numbers that look calibrated
and are not. Enabling noise without a mechanism therefore raises rather than
silently passing data through.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.models import CohortBucketing, CommunityAggregate, PublicAggregateView

# A cohort of one *is* an individual, so publishing it breaches INV-EXPOSE-1
# outright, and a cohort of zero has nothing to publish. This is an arithmetic
# floor derived from an existing invariant -- it is emphatically **not** a
# suggested threshold. The usable value is OPEN-1, is larger, and is the
# owner's to set per community.
ABSOLUTE_MINIMUM_THRESHOLD = 2


class PrivacyConfigurationError(Exception):
    """The gate was configured in a way that cannot be safe."""


class NoiseMechanismNotConfigured(PrivacyConfigurationError):
    """Noise was enabled without the parameters a mechanism would need."""


class NoiseMechanismNotImplemented(PrivacyConfigurationError):
    """Noise was enabled and parameterised, but no mechanism exists yet."""


@dataclass(frozen=True)
class NoiseConfig:
    """Configuration for `PrivacyGate.apply_noise`.

    Defaults to disabled, which is the only state that currently works. The
    fields exist so that a deployment cannot *quietly* run without noise: the
    absence has to be visible in configuration rather than inferred from the
    code having never grown the feature.
    """

    enabled: bool = False
    mechanism: str | None = None
    epsilon: float | None = None


@dataclass(frozen=True)
class PrivacyGate:
    """Suppression and (eventually) noise, applied per slice on every read.

    Construct one per community: `min_cohort_threshold` is a per-community
    value with no safe default (OPEN-1), so it is a required argument here as
    it is on `Community`.
    """

    min_cohort_threshold: int
    bucketing: CohortBucketing
    noise: NoiseConfig = NoiseConfig()

    def __post_init__(self) -> None:
        if self.min_cohort_threshold < ABSOLUTE_MINIMUM_THRESHOLD:
            raise PrivacyConfigurationError(
                f"min_cohort_threshold must be at least {ABSOLUTE_MINIMUM_THRESHOLD}: "
                f"a smaller cohort is an individual, and publishing it breaches "
                f"INV-EXPOSE-1. The usable value is larger and is set per community "
                f"(OPEN-1 in docs/04_PRIVACY_INVARIANTS.md)."
            )

    def suppress_if_below_threshold(
        self, aggregate: CommunityAggregate | None
    ) -> CommunityAggregate | None:
        """Return the aggregate if it may be published, otherwise None.

        Accepts `None` and returns `None` for it. That is not defensive
        padding: INV-EXPOSE-3 requires a below-threshold slice and an absent
        slice to be indistinguishable, and the cheapest way to guarantee that
        is to give callers one function whose output is already identical in
        both cases. A caller that has to write `if aggregate is None` before
        calling the gate is a caller that can accidentally answer differently.
        """
        if aggregate is None:
            return None
        if not aggregate.is_above_threshold(self.min_cohort_threshold):
            return None
        return aggregate

    def apply_noise(self, aggregate: CommunityAggregate) -> CommunityAggregate:
        """Placeholder. Returns the aggregate unchanged when noise is disabled.

        **This is a no-op, not a privacy control.** Threshold suppression alone
        does not defend against differencing across successive releases
        (OPEN-2); this method is where that defence will go, and until it does,
        the defence is absent.

        Raises:
            NoiseMechanismNotConfigured: noise enabled without mechanism/epsilon.
            NoiseMechanismNotImplemented: noise enabled and parameterised, but
                no mechanism has been chosen or built.
        """
        if not self.noise.enabled:
            return aggregate

        if self.noise.mechanism is None or self.noise.epsilon is None:
            raise NoiseMechanismNotConfigured(
                "Noise is enabled but mechanism and epsilon are unset. Neither has a "
                "default: see OPEN-3 in docs/04_PRIVACY_INVARIANTS.md."
            )
        raise NoiseMechanismNotImplemented(
            f"Noise is enabled with mechanism {self.noise.mechanism!r}, but no noise "
            f"mechanism is implemented. The choice between threshold suppression and "
            f"differential privacy is unresolved (OPEN-3) and epsilon must not be "
            f"guessed. Disable noise or implement the mechanism -- do not remove this "
            f"check."
        )

    def public_view(self, aggregate: CommunityAggregate | None) -> PublicAggregateView | None:
        """The only supported read path for an aggregate.

        Suppress, then noise, then project. Returns `None` for a suppressed
        slice and for an absent one, identically (INV-EXPOSE-3).

        A route rendering this must map `None` to the same status, body and
        headers it would return for a slice that does not exist -- `404` per
        `docs/03_API_CONTRACT.md`. Timing is a route-level concern this method
        cannot settle on its own; both branches here do the same negligible
        work, but a route that skips a database lookup for the absent case
        remains distinguishable by latency.
        """
        permitted = self.suppress_if_below_threshold(aggregate)
        if permitted is None:
            return None
        return self.apply_noise(permitted).to_public_view(self.bucketing)

    def public_views(
        self, aggregates: Iterable[CommunityAggregate]
    ) -> list[PublicAggregateView]:
        """Project a collection, dropping suppressed slices silently.

        No placeholder entries, no "hidden" markers, and no count of what was
        withheld -- any of those republishes the existence of a small cohort,
        which is the thing suppression is for.
        """
        views = (self.public_view(aggregate) for aggregate in aggregates)
        return [view for view in views if view is not None]
