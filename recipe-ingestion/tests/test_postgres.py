"""Integration tests against the real Dockerized Postgres instance."""
import pytest

from app.db.postgres import (
    get_alias,
    get_recipe_by_id,
    get_recipe_by_url_hash,
    insert_recipe,
    search_recipes_by_name,
    upsert_alias,
)
from app.models.recipe import Ingredient, Instruction, RecipeBase

# pg fixture provided by tests/conftest.py

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_recipe(
    title: str = "Spaghetti Carbonara",
    source_url: str = "https://example.com/spaghetti-carbonara",
    **kwargs,
) -> RecipeBase:
    return RecipeBase(
        title=title,
        source_url=source_url,
        ingredients=[Ingredient(name="pasta", quantity="200", unit="g")],
        instructions=[Instruction(step=1, text="Boil water and cook pasta.")],
        **kwargs,
    )


_HASH_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_HASH_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_insert_and_get_by_url_hash(pg):
    recipe = _make_recipe()
    inserted = await insert_recipe(recipe, _HASH_A, "<html/>", "v1", conn=pg)

    assert inserted.id is not None
    assert inserted.title == "Spaghetti Carbonara"
    assert inserted.url_hash == _HASH_A
    assert len(inserted.ingredients) == 1
    assert inserted.ingredients[0].name == "pasta"
    assert inserted.instructions[0].step == 1

    fetched = await get_recipe_by_url_hash(_HASH_A, conn=pg)
    assert fetched is not None
    assert fetched.id == inserted.id


async def test_get_recipe_by_id(pg):
    recipe = _make_recipe()
    inserted = await insert_recipe(recipe, _HASH_A, "<html/>", "v1", conn=pg)

    fetched = await get_recipe_by_id(inserted.id, conn=pg)
    assert fetched is not None
    assert fetched.id == inserted.id
    assert fetched.title == inserted.title


async def test_insert_conflict_returns_original_row(pg):
    recipe = _make_recipe()
    first = await insert_recipe(recipe, _HASH_A, "<html/>", "v1", conn=pg)

    # Same url_hash — ON CONFLICT DO NOTHING should return the original row
    second = await insert_recipe(recipe, _HASH_A, "<html>different</html>", "v2", conn=pg)

    assert first.id == second.id
    assert second.parser_version == "v1"  # original, not the conflicting insert


async def test_get_recipe_by_url_hash_missing(pg):
    result = await get_recipe_by_url_hash("nonexistent-hash", conn=pg)
    assert result is None


async def test_get_recipe_by_id_missing(pg):
    import uuid
    result = await get_recipe_by_id(str(uuid.uuid4()), conn=pg)
    assert result is None


async def test_upsert_alias_inserts_then_increments(pg):
    recipe = _make_recipe()
    inserted = await insert_recipe(recipe, _HASH_A, "<html/>", "v1", conn=pg)
    rid = inserted.id

    await upsert_alias(rid, "spaghetti-carbonara", "Spaghetti Carbonara", conn=pg)
    row = await pg.fetchrow(
        "SELECT hit_count FROM recipe_name_aliases WHERE normalized_name = $1",
        "spaghetti-carbonara",
    )
    assert row["hit_count"] == 1

    # Second upsert on same normalized_name → hit_count increments
    await upsert_alias(rid, "spaghetti-carbonara", "Spaghetti Carbonara", conn=pg)
    row = await pg.fetchrow(
        "SELECT hit_count FROM recipe_name_aliases WHERE normalized_name = $1",
        "spaghetti-carbonara",
    )
    assert row["hit_count"] == 2


async def test_get_alias_returns_recipe_id(pg):
    recipe = _make_recipe()
    inserted = await insert_recipe(recipe, _HASH_A, "<html/>", "v1", conn=pg)
    await upsert_alias(inserted.id, "spaghetti-carbonara", "Spaghetti Carbonara", conn=pg)

    result = await get_alias("spaghetti-carbonara", conn=pg)
    assert result == inserted.id


async def test_get_alias_returns_none_for_unknown(pg):
    result = await get_alias("this-does-not-exist", conn=pg)
    assert result is None


async def test_search_recipes_by_name_finds_match(pg):
    await insert_recipe(
        _make_recipe(
            title="Chicken Tikka Masala",
            source_url="https://example.com/chicken-tikka",
        ),
        _HASH_A,
        "<html/>",
        "v1",
        conn=pg,
    )
    await insert_recipe(
        _make_recipe(
            title="Beef Bourguignon",
            source_url="https://example.com/beef-bourguignon",
        ),
        _HASH_B,
        "<html/>",
        "v1",
        conn=pg,
    )

    results = await search_recipes_by_name("chicken", conn=pg)
    assert len(results) == 1
    record, rank = results[0]
    assert record.title == "Chicken Tikka Masala"
    assert rank > 0


async def test_search_recipes_by_name_empty_for_no_match(pg):
    await insert_recipe(
        _make_recipe(title="Beef Stew", source_url="https://example.com/beef-stew"),
        _HASH_A,
        "<html/>",
        "v1",
        conn=pg,
    )
    results = await search_recipes_by_name("sushi", conn=pg)
    assert results == []


async def test_search_recipes_by_name_respects_limit(pg):
    urls = [f"https://example.com/soup-{i}" for i in range(4)]
    hashes = [f"{'a' * 63}{i}" for i in range(4)]
    for i, (url, h) in enumerate(zip(urls, hashes)):
        await insert_recipe(
            _make_recipe(title=f"Tomato Soup {i}", source_url=url),
            h,
            "<html/>",
            "v1",
            conn=pg,
        )

    results = await search_recipes_by_name("tomato", limit=2, conn=pg)
    assert len(results) == 2


async def test_insert_preserves_optional_fields(pg):
    recipe = _make_recipe(
        servings=4,
        total_time_min=30,
        cuisine="Italian",
        difficulty="easy",
        nutrition={"calories": 500},
        image_url="https://example.com/img.jpg",
    )
    inserted = await insert_recipe(recipe, _HASH_A, "<html/>", "v1", conn=pg)

    assert inserted.servings == 4
    assert inserted.total_time_min == 30
    assert inserted.cuisine == "Italian"
    assert inserted.difficulty == "easy"
    assert inserted.nutrition == {"calories": 500}
    assert inserted.image_url == "https://example.com/img.jpg"
