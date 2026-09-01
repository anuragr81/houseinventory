"""
app/api/facets.py
------------------
`GET /facets` -- the platform's facet catalogue.

A client needs this before it can build a founding request: `facet_keys` in
`POST /communities` selects from exactly this list (`docs/03_API_CONTRACT.md`,
"Founding a community").
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_catalogue
from app.api.schemas import FacetOut
from app.domain.facet_catalogue import FacetCatalogue

router = APIRouter(tags=["facets"])


@router.get("/facets", response_model=list[FacetOut])
def list_facets(catalogue: FacetCatalogue = Depends(get_catalogue)) -> list[FacetOut]:
    return [
        FacetOut(
            key=definition.key,
            name=definition.name,
            value_type=definition.value_type,
            scale_min=definition.scale_min,
            scale_max=definition.scale_max,
        )
        for definition in catalogue.definitions
    ]
