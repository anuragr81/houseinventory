"""
app/api/communities.py
-----------------------
`GET /communities`, `GET /communities/{slug}`, and `POST /communities`.

The two reads are public and neither goes through `PrivacyGate`: that gate
exists to suppress a `CommunityAggregate` below threshold (INV-EXPOSE-4), and
nothing returned by either is an aggregate, a cohort size, or contribution
data. A `SEEDING` community is visible here on purpose -- `docs/03_API_
CONTRACT.md` is explicit that `SEEDING` means "exposes no aggregates yet",
not "hidden".

`POST /communities` is the one write here, and an ordinary authenticated
request now that founding no longer needs five distinct people (see the rule
history in `docs/03_API_CONTRACT.md`, "Founding a community"): the decision
logic (`community_founding.found_community`) and the atomic write
(`founding_store.persist_founding`) both already existed and are both
already tested; this route is what was missing -- a session identifying the
founder, from `get_current_user_id`.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_catalogue, get_current_user_id, get_session
from app.api.schemas import (
    CommunityDetailOut,
    CommunityFacetOut,
    CommunitySummaryOut,
    FoundCommunityIn,
)
from app.domain.facet_catalogue import FacetCatalogue, UnknownFacetKeyError
from app.persistence.founding_store import SlugAlreadyTakenError, persist_founding
from app.persistence.repositories import CommunityRepository, FacetRepository
from app.services.community_founding import (
    FoundingContribution,
    FoundingError,
    found_community,
)

router = APIRouter(tags=["communities"])


@router.get("/communities", response_model=list[CommunitySummaryOut])
def list_communities(
    session: Session = Depends(get_session),
) -> list[CommunitySummaryOut]:
    return [
        CommunitySummaryOut(
            community_id=community.community_id,
            slug=community.slug,
            status=community.status,
        )
        for community in CommunityRepository(session).list_all()
    ]


@router.get("/communities/{slug}", response_model=CommunityDetailOut)
def get_community(
    slug: str, session: Session = Depends(get_session)
) -> CommunityDetailOut:
    community = CommunityRepository(session).get_by_slug(slug)
    if community is None:
        raise HTTPException(status_code=404, detail="Community not found.")

    facets = FacetRepository(session).for_community(community.community_id)
    return CommunityDetailOut(
        community_id=community.community_id,
        slug=community.slug,
        status=community.status,
        facets=[
            CommunityFacetOut(
                facet_id=facet.facet_id,
                name=facet.name,
                value_type=facet.value_type,
                scale_min=facet.scale_min,
                scale_max=facet.scale_max,
            )
            for facet in facets
        ],
    )


@router.post("/communities", response_model=CommunitySummaryOut, status_code=201)
def found(
    payload: FoundCommunityIn,
    founder_id: UUID = Depends(get_current_user_id),
    session: Session = Depends(get_session),
    catalogue: FacetCatalogue = Depends(get_catalogue),
) -> CommunitySummaryOut:
    now = datetime.now(UTC)
    contributions = [
        FoundingContribution(
            place_id=contribution.place_id,
            facet_scores=contribution.facet_scores,
            free_text=contribution.free_text,
        )
        for contribution in payload.contributions
    ]

    # FoundingError and UnknownFacetKeyError messages are written not to name
    # a specific user, contribution, or facet score (see their docstrings),
    # so surfacing them as-is keeps that rule enforced in one place rather
    # than requiring this route to remember it.
    try:
        result = found_community(
            payload.slug,
            payload.min_cohort_threshold,
            frozenset(payload.facet_keys),
            catalogue,
            founder_id,
            contributions,
            now,
        )
    except (FoundingError, UnknownFacetKeyError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        persist_founding(session, result, now)
    except SlugAlreadyTakenError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()

    return CommunitySummaryOut(
        community_id=result.community.community_id,
        slug=result.community.slug,
        status=result.community.status,
    )
