import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import recipe_client as rc
from recipe_client import (
    RecipeFetchError,
    RecipeNotFoundError,
    RecipeServiceError,
    RecipeUnparseableError,
    resolve_recipe,
)

FAKE_RECIPE = {
    "id": "abc123",
    "title": "Spaghetti Carbonara",
    "source_url": "https://example.com/carbonara",
    "ingredients": [
        {"name": "spaghetti", "quantity": "400", "unit": "g"},
        {"name": "pancetta", "quantity": "200", "unit": "g", "notes": "diced"},
        {"name": "eggs", "quantity": "4", "unit": None},
    ],
    "instructions": [
        {"step": 1, "text": "Boil spaghetti."},
        {"step": 2, "text": "Fry pancetta."},
        {"step": 3, "text": "Mix eggs and cheese."},
    ],
    "servings": 4,
    "total_time_min": 25,
    "cuisine": "Italian",
    "difficulty": "medium",
}


def _mock_client(status_code: int, body: dict | None = None, exc: Exception | None = None):
    mock = MagicMock()
    if exc is not None:
        mock.post = AsyncMock(side_effect=exc)
    else:
        resp = MagicMock()
        resp.status_code = status_code
        resp.is_success = 200 <= status_code < 300
        resp.json = MagicMock(return_value=body or {})
        mock.post = AsyncMock(return_value=resp)
    return mock


@pytest.fixture(autouse=True)
def reset_client():
    rc._client = None
    yield
    rc._client = None


@pytest.mark.asyncio
async def test_resolve_recipe_success():
    rc._client = _mock_client(200, FAKE_RECIPE)
    result = await resolve_recipe("https://example.com/carbonara")
    assert result["title"] == "Spaghetti Carbonara"
    rc._client.post.assert_awaited_once_with(
        "/recipes/resolve", json={"input": "https://example.com/carbonara"}
    )


@pytest.mark.asyncio
async def test_resolve_recipe_404_raises_not_found():
    rc._client = _mock_client(404)
    with pytest.raises(RecipeNotFoundError):
        await resolve_recipe("https://example.com/missing")


@pytest.mark.asyncio
async def test_resolve_recipe_422_raises_unparseable():
    rc._client = _mock_client(422, {"detail": "invalid input"})
    with pytest.raises(RecipeUnparseableError, match="invalid input"):
        await resolve_recipe("not a real input")


@pytest.mark.asyncio
async def test_resolve_recipe_502_raises_fetch_error():
    rc._client = _mock_client(502, {"detail": "upstream error"})
    with pytest.raises(RecipeFetchError, match="upstream error"):
        await resolve_recipe("https://example.com/recipe")


@pytest.mark.asyncio
async def test_resolve_recipe_network_error_raises_service_error():
    rc._client = _mock_client(0, exc=httpx.RequestError("connection refused"))
    with pytest.raises(RecipeServiceError):
        await resolve_recipe("https://example.com/recipe")


@pytest.mark.asyncio
async def test_resolve_recipe_unexpected_status_raises_service_error():
    rc._client = _mock_client(500)
    with pytest.raises(RecipeServiceError, match="unexpected status 500"):
        await resolve_recipe("https://example.com/recipe")
