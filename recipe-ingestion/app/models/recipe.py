from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class InputType(str, Enum):
    url = "url"
    name = "name"


class RecipeInput(BaseModel):
    raw: str


class NormalizedInput(BaseModel):
    input_type: InputType
    raw: str
    canonical_url: str | None = None
    url_hash: str | None = None
    normalized_name: str | None = None


class Ingredient(BaseModel):
    name: str
    quantity: str | None = None
    unit: str | None = None
    notes: str | None = None


class Instruction(BaseModel):
    step: int
    text: str


class RecipeBase(BaseModel):
    title: str
    source_url: str | None = None
    ingredients: list[Ingredient]
    instructions: list[Instruction]
    servings: int | None = None
    total_time_min: int | None = None
    cuisine: str | None = None
    difficulty: str | None = None
    nutrition: dict[str, Any] | None = None
    image_url: str | None = None


class RecipeRecord(RecipeBase):
    id: str          # uuid stored as str
    url_hash: str | None = None
    parser_version: str | None = None


class ResolveRequest(BaseModel):
    input: str = Field(min_length=1, max_length=2000)


class ResolveResult(BaseModel):
    """Result of resolving a dish name to an existing recipe or a URL to parse."""
    normalized_name: str
    match_type: Literal["alias_exact", "fts", "web_search"]
    # Exactly one of these is set:
    recipe_id: str | None = None    # alias_exact / fts — already in DB
    source_url: str | None = None   # web_search — caller must parse
