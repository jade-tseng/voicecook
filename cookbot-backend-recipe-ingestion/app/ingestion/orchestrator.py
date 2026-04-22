"""Recipe ingestion orchestrator — composes all pipeline sections A–E.

Implements the 10-step resolve_recipe pipeline:
  URL path:  Redis → Postgres → Parser → write DB → write Redis → return
  Name path: Redis alias → resolver → (alias/fts: Postgres) |
                                       (web_search: URL path) → return
"""
import logging
import time

from app.db import postgres, redis
from app.db.postgres import get_pool
from app.ingestion import parser, resolver
from app.ingestion.input import InputType, normalize_input, normalize_url
from app.models.recipe import RecipeRecord

logger = logging.getLogger(__name__)


class RecipeNotFound(Exception):
    """Raised when name resolution exhausts all tiers and finds nothing."""


# ---------------------------------------------------------------------------
# Internal URL branch (shared by URL input path and web_search name path)
# ---------------------------------------------------------------------------

async def _resolve_url_branch(
    canonical_url: str,
    url_hash: str,
    normalized_name: str | None = None,
    original_name: str | None = None,
) -> tuple[RecipeRecord, str]:
    """Redis → Postgres → Parser for a known URL.

    If *normalized_name* is supplied (web_search path), also writes alias
    records in Postgres and Redis after the recipe is secured.

    Returns (RecipeRecord, cache_layer) where cache_layer is one of
    "redis", "postgres", "parsed".
    """
    # --- Redis hit ---
    record = await redis.get_recipe_by_url_hash(url_hash)
    if record:
        if normalized_name:
            await postgres.upsert_alias(record.id, normalized_name, original_name or normalized_name)
            await redis.cache_alias(normalized_name, record.id)
        return record, "redis"

    # --- Postgres hit ---
    record = await postgres.get_recipe_by_url_hash(url_hash)
    if record:
        await redis.cache_recipe(record)
        if normalized_name:
            await postgres.upsert_alias(record.id, normalized_name, original_name or normalized_name)
            await redis.cache_alias(normalized_name, record.id)
        return record, "postgres"

    # --- Full miss: fetch, parse, persist ---
    recipe, raw_html = await parser.parse_url(canonical_url)

    async with get_pool().acquire() as conn:
        async with conn.transaction():
            record = await postgres.insert_recipe(
                recipe, url_hash, raw_html, parser.PARSER_VERSION, conn=conn
            )
            if normalized_name:
                await postgres.upsert_alias(
                    record.id, normalized_name, original_name or normalized_name, conn=conn
                )

    # Redis writes after the DB commit
    await redis.cache_recipe(record)
    if normalized_name:
        await redis.cache_alias(normalized_name, record.id)

    return record, "parsed"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def resolve_recipe(raw_input: str) -> RecipeRecord:
    """Resolve raw user input (URL or dish name) to a RecipeRecord.

    Raises:
        RecipeNotFound    — name path exhausted all tiers
        parser.FetchError — network failure during parse
        parser.ExtractError — HTML received but no recipe extractable
        parser.ParseError — other parse failure
    """
    start = time.monotonic()
    ni = normalize_input(raw_input)
    log_ctx: dict = {}

    try:
        # ================================================================
        # URL path
        # ================================================================
        if ni.input_type == InputType.url:
            log_ctx["input_type"] = "url"
            log_ctx["normalized_key"] = ni.url_hash

            record, cache_layer = await _resolve_url_branch(
                ni.canonical_url, ni.url_hash
            )
            log_ctx["cache_layer"] = cache_layer
            log_ctx["outcome"] = "hit" if cache_layer != "parsed" else "parsed"
            return record

        # ================================================================
        # Name path
        # ================================================================
        log_ctx["input_type"] = "name"
        log_ctx["normalized_key"] = ni.normalized_name

        # Step 3a — Redis name cache
        cached_id = await redis.get_recipe_id_by_name(ni.normalized_name)
        if cached_id:
            cached_record = await redis.get_recipe_by_id(cached_id)
            if cached_record:
                log_ctx["cache_layer"] = "redis"
                log_ctx["outcome"] = "hit"
                return cached_record
            # Stale pointer — body evicted; fall through to resolver
            log_ctx["cache_layer"] = "redis_stale"

        # Step 3b — Resolver (alias → FTS → web_search)
        result = await resolver.resolve_name(raw_input.strip())

        if result is None:
            log_ctx["outcome"] = "not_found"
            raise RecipeNotFound(f"No recipe found for: {raw_input!r}")

        log_ctx["match_type"] = result.match_type

        if result.match_type in ("alias_exact", "fts"):
            record = await postgres.get_recipe_by_id(result.recipe_id)
            await redis.cache_recipe(record)
            await redis.cache_alias(ni.normalized_name, record.id)
            log_ctx["cache_layer"] = "postgres"
            log_ctx["outcome"] = "hit"
            return record

        # web_search — result.source_url must be parsed
        canonical_url, url_hash = normalize_url(result.source_url)
        record, cache_layer = await _resolve_url_branch(
            canonical_url,
            url_hash,
            normalized_name=ni.normalized_name,
            original_name=raw_input.strip(),
        )
        log_ctx["cache_layer"] = cache_layer
        log_ctx["outcome"] = "parsed"
        return record

    except RecipeNotFound as exc:
        log_ctx["error_type"] = type(exc).__name__
        raise
    except Exception as exc:
        log_ctx["outcome"] = "error"
        log_ctx["error_type"] = type(exc).__name__
        logger.exception("resolve_recipe error for %r", raw_input)
        raise
    finally:
        log_ctx["latency_ms"] = round((time.monotonic() - start) * 1000, 1)
        logger.info("resolve_recipe", extra=log_ctx)
