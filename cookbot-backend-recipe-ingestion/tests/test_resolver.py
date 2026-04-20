"""Integration tests for the name resolver against real Postgres."""
from unittest.mock import AsyncMock

import pytest

from app.db.postgres import insert_recipe, upsert_alias
from app.ingestion import resolver as resolver_mod
from app.ingestion.resolver import resolve_name
from app.models.recipe import Ingredient, Instruction, RecipeBase

# pg fixture provided by tests/conftest.py

# Stable hashes for the three seed recipes
_HASH_TIKKA  = "t" * 64
_HASH_BUTTER = "b" * 64
_HASH_PAD    = "p" * 64


def _recipe(title: str, url: str) -> RecipeBase:
    return RecipeBase(
        title=title,
        source_url=url,
        ingredients=[Ingredient(name="ingredient")],
        instructions=[Instruction(step=1, text="Cook it.")],
    )


@pytest.fixture
async def seeded(pg):
    """Insert three recipes and one alias; yield the pg connection."""
    tikka = await insert_recipe(
        _recipe("Chicken Tikka Masala", "https://example.com/tikka"),
        _HASH_TIKKA, "<html/>", "v1", conn=pg,
    )
    await insert_recipe(
        _recipe("Butter Chicken", "https://example.com/butter-chicken"),
        _HASH_BUTTER, "<html/>", "v1", conn=pg,
    )
    await insert_recipe(
        _recipe("Pad Thai", "https://example.com/pad-thai"),
        _HASH_PAD, "<html/>", "v1", conn=pg,
    )
    # Alias "chicken-masala-tikka" → tikka recipe
    from app.ingestion.input import normalize_name
    alias = normalize_name("Chicken Tikka Masala")   # "chicken-masala-tikka"
    await upsert_alias(tikka.id, alias, "Chicken Tikka Masala", conn=pg)
    return pg, tikka.id


# ---------------------------------------------------------------------------
# Alias exact match
# ---------------------------------------------------------------------------

async def test_alias_exact_match(seeded):
    pg, tikka_id = seeded
    result = await resolve_name("Chicken Tikka Masala", conn=pg)

    assert result is not None
    assert result.match_type == "alias_exact"
    assert result.recipe_id == tikka_id
    assert result.source_url is None


async def test_alias_exact_match_case_insensitive(seeded):
    """Uppercase variant should still hit the same alias after token sort."""
    pg, tikka_id = seeded
    result = await resolve_name("chicken TIKKA masala", conn=pg)

    assert result is not None
    assert result.match_type == "alias_exact"
    assert result.recipe_id == tikka_id


async def test_alias_exact_match_token_sorted(seeded):
    """Word-order variant should still hit via token-sorted normalization."""
    pg, tikka_id = seeded
    result = await resolve_name("masala tikka chicken", conn=pg)

    assert result is not None
    assert result.match_type == "alias_exact"
    assert result.recipe_id == tikka_id


# ---------------------------------------------------------------------------
# FTS match
# ---------------------------------------------------------------------------

async def test_fts_match_no_alias(seeded):
    """'tikka' has no alias but FTS should match 'Chicken Tikka Masala'."""
    pg, tikka_id = seeded
    result = await resolve_name("tikka", conn=pg)

    assert result is not None
    assert result.match_type == "fts"
    assert result.recipe_id == tikka_id
    assert result.source_url is None


async def test_fts_match_returns_top_hit(seeded):
    """'pad thai' has no alias; FTS should match 'Pad Thai'."""
    pg, _ = seeded
    result = await resolve_name("pad thai", conn=pg)

    assert result is not None
    assert result.match_type == "fts"
    assert result.recipe_id is not None


# ---------------------------------------------------------------------------
# Complete miss → web search stub → None
# ---------------------------------------------------------------------------

async def test_gibberish_returns_none(seeded):
    """No alias, no FTS hit, web_search raises NotImplementedError → None."""
    pg, _ = seeded
    result = await resolve_name("xkzqwerty flibbertigibbet zorblax", conn=pg)
    assert result is None


# ---------------------------------------------------------------------------
# Web search path (monkeypatched)
# ---------------------------------------------------------------------------

async def test_web_search_path(seeded, monkeypatch):
    """When web_search returns a URL, resolve_name returns web_search result."""
    pg, _ = seeded
    monkeypatch.setattr(
        resolver_mod,
        "web_search",
        AsyncMock(return_value="https://example.com/new-recipe"),
    )

    # Use a query that has no alias and no FTS match
    result = await resolve_name("obscure ancient dish", conn=pg)

    assert result is not None
    assert result.match_type == "web_search"
    assert result.source_url == "https://example.com/new-recipe"
    assert result.recipe_id is None


async def test_web_search_returns_none_propagates(seeded, monkeypatch):
    """When web_search returns None, resolve_name also returns None."""
    pg, _ = seeded
    monkeypatch.setattr(
        resolver_mod,
        "web_search",
        AsyncMock(return_value=None),
    )
    result = await resolve_name("obscure ancient dish", conn=pg)
    assert result is None


# ---------------------------------------------------------------------------
# ResolveResult shape
# ---------------------------------------------------------------------------

async def test_resolve_result_normalized_name_is_token_sorted(seeded):
    """normalized_name in the result reflects the token-sorted form."""
    pg, _ = seeded
    result = await resolve_name("Chicken Tikka Masala", conn=pg)

    assert result is not None
    assert result.normalized_name == "chicken-masala-tikka"
