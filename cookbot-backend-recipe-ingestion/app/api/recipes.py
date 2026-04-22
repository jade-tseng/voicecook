from fastapi import APIRouter

from app.ingestion.orchestrator import resolve_recipe
from app.models.recipe import RecipeRecord, ResolveRequest

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.post("/resolve", response_model=RecipeRecord)
async def resolve(body: ResolveRequest) -> RecipeRecord:
    return await resolve_recipe(body.input)
