"""
app/api/communities.py
-----------------------
`GET /communities` and `GET /communities/{slug}`.

Both are public and read-only, and neither goes through `PrivacyGate`: that
gate exists to suppress a `CommunityAggregate` below threshold (INV-EXPOSE-4),
and nothing returned here is an aggregate, a cohort size, or contribution
data. A `SEEDING` community is visible here on purpose -- `docs/03_API_
CONTRACT.md` is explicit that `SEEDING` means "exposes no aggregates yet",
not "hidden".
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import CommunityDetailOut, CommunityFacetOut, CommunitySummaryOut
from app.persistence.repositories import CommunityRepository, FacetRepository

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
