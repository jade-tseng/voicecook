import json
import uuid
from typing import Any

import asyncpg

from app.config import settings
from app.models.recipe import Ingredient, Instruction, RecipeBase, RecipeRecord

_pool: asyncpg.Pool | None = None


# ---------------------------------------------------------------------------
# Codec helpers
# ---------------------------------------------------------------------------

async def _setup_codecs(conn: asyncpg.Connection) -> None:
    for pg_type in ("json", "jsonb"):
        await conn.set_type_codec(
            pg_type,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


# ---------------------------------------------------------------------------
# Pool lifecycle
# ---------------------------------------------------------------------------

async def init_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
    _pool = await asyncpg.create_pool(
        settings.database_url,
        init=_setup_codecs,
        min_size=2,
        max_size=10,
    )


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Postgres pool not initialized — call init_pool() first")
    return _pool


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------

def _row_to_recipe(row: asyncpg.Record) -> RecipeRecord:
    return RecipeRecord(
        id=str(row["id"]),
        title=row["title"],
        source_url=row["source_url"],
        url_hash=row["url_hash"],
        ingredients=[Ingredient.model_validate(i) for i in (row["ingredients"] or [])],
        instructions=[Instruction.model_validate(i) for i in (row["instructions"] or [])],
        servings=row["servings"],
        total_time_min=row["total_time_min"],
        cuisine=row["cuisine"],
        difficulty=row["difficulty"],
        nutrition=row["nutrition"],
        image_url=row["image_url"],
        parser_version=row["parser_version"],
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

_Conn = asyncpg.Connection | asyncpg.Pool


async def get_recipe_by_url_hash(
    url_hash: str,
    conn: _Conn | None = None,
) -> RecipeRecord | None:
    c = conn or get_pool()
    row = await c.fetchrow(
        "SELECT * FROM recipes WHERE url_hash = $1",
        url_hash,
    )
    return _row_to_recipe(row) if row else None


async def get_recipe_by_id(
    recipe_id: str,
    conn: _Conn | None = None,
) -> RecipeRecord | None:
    c = conn or get_pool()
    row = await c.fetchrow(
        "SELECT * FROM recipes WHERE id = $1",
        uuid.UUID(recipe_id),
    )
    return _row_to_recipe(row) if row else None


async def get_alias(
    normalized_name: str,
    conn: _Conn | None = None,
) -> str | None:
    c = conn or get_pool()
    row = await c.fetchrow(
        "SELECT recipe_id FROM recipe_name_aliases WHERE normalized_name = $1",
        normalized_name,
    )
    return str(row["recipe_id"]) if row else None


async def search_recipes_by_name(
    query: str,
    limit: int = 5,
    conn: _Conn | None = None,
) -> list[tuple[RecipeRecord, float]]:
    c = conn or get_pool()
    rows = await c.fetch(
        """
        SELECT *, ts_rank(search_vector, plainto_tsquery('english', $1)) AS rank
        FROM   recipes
        WHERE  search_vector @@ plainto_tsquery('english', $1)
        ORDER  BY rank DESC
        LIMIT  $2
        """,
        query,
        limit,
    )
    return [(_row_to_recipe(row), float(row["rank"])) for row in rows]


async def insert_recipe(
    recipe: RecipeBase,
    url_hash: str,
    raw_html: str,
    parser_version: str,
    conn: _Conn | None = None,
) -> RecipeRecord:
    if not recipe.source_url:
        raise ValueError("source_url is required for DB insertion")
    c = conn or get_pool()

    row = await c.fetchrow(
        """
        INSERT INTO recipes (
            source_url, url_hash, title,
            ingredients, instructions,
            servings, total_time_min, cuisine, difficulty,
            nutrition, image_url, raw_html, parser_version
        ) VALUES (
            $1, $2, $3,
            $4, $5,
            $6, $7, $8, $9,
            $10, $11, $12, $13
        )
        ON CONFLICT (url_hash) DO NOTHING
        RETURNING *
        """,
        recipe.source_url,
        url_hash,
        recipe.title,
        [i.model_dump(mode="json") for i in recipe.ingredients],
        [i.model_dump(mode="json") for i in recipe.instructions],
        recipe.servings,
        recipe.total_time_min,
        recipe.cuisine,
        recipe.difficulty,
        recipe.nutrition,
        recipe.image_url,
        raw_html,
        parser_version,
    )

    if row is None:
        # conflict — return the pre-existing row
        row = await c.fetchrow(
            "SELECT * FROM recipes WHERE url_hash = $1",
            url_hash,
        )

    return _row_to_recipe(row)


async def upsert_alias(
    recipe_id: str,
    normalized_name: str,
    original_name: str,
    conn: _Conn | None = None,
) -> None:
    c = conn or get_pool()
    await c.execute(
        """
        INSERT INTO recipe_name_aliases (recipe_id, normalized_name, original_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (normalized_name)
        DO UPDATE SET hit_count = recipe_name_aliases.hit_count + 1
        """,
        uuid.UUID(recipe_id),
        normalized_name,
        original_name,
    )
