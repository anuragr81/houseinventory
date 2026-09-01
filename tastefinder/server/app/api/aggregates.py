"""
app/api/aggregates.py
----------------------
`GET /communities/{slug}/places/{place_id}/aggregate`.

The first route that reads a `CommunityAggregate` at all, and so the first
place `PrivacyGate` is exercised over HTTP: suppression (`INV-EXPOSE-4`) and
the requirement that a suppressed slice and an absent slice be
indistinguishable (`INV-EXPOSE-3`) both apply here for the first time.

`GET /communities/{slug}/aggregates?bbox=...` (docs/03_API_CONTRACT.md) is not
built here -- it needs a new repository method this route does not, and is a
separate piece of work.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_bucketing, get_session
from app.api.schemas import AggregateOut, FacetStatOut
from app.domain.models import CohortBucketing
from app.persistence.repositories import AggregateRepository, CommunityRepository
from app.services.privacy_gate import PrivacyGate

router = APIRouter(tags=["aggregates"])


@router.get(
    "/communities/{slug}/places/{place_id}/aggregate",
    response_model=AggregateOut,
)
def get_place_aggregate(
    slug: str,
    place_id: str,
    session: Session = Depends(get_session),
    bucketing: CohortBucketing = Depends(get_bucketing),
) -> AggregateOut:
    community = CommunityRepository(session).get_by_slug(slug)

    # A community's existence is already public information (GET /communities
    # lists every slug), so branching on it here reveals nothing suppression
    # is meant to hide. What INV-EXPOSE-3 actually requires -- a below-
    # threshold slice and a place with no data at all, within the *same*
    # community, returning the same response -- is guaranteed below: both
    # collapse to PrivacyGate.public_view returning None, and from there to
    # the identical 404 raised once, in one place.
    view = None
    if community is not None:
        raw = AggregateRepository(session).get(community.community_id, place_id)
        gate = PrivacyGate(
            min_cohort_threshold=community.min_cohort_threshold, bucketing=bucketing
        )
        view = gate.public_view(raw)

    if view is None:
        raise HTTPException(status_code=404, detail="Aggregate not found.")

    return AggregateOut(
        community_id=view.community_id,
        place_id=view.place_id,
        facet_summaries=[
            FacetStatOut(
                facet_id=stat.facet_id, mean=stat.mean, variance=stat.variance, n=stat.n
            )
            for stat in view.facet_summaries
        ],
        cohort_size_bucket=view.cohort_size_bucket,
    )
