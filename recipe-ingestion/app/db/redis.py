import logging

import redis.asyncio as aioredis
import redis.exceptions

from app.config import settings
from app.models.recipe import RecipeRecord

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def init_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis client not initialized — call init_redis() first")
    return _redis


# ---------------------------------------------------------------------------
# Key builders
# ---------------------------------------------------------------------------

def key_url(url_hash: str) -> str:
    return f"recipe:url:{url_hash}"


def key_name(normalized_name: str) -> str:
    return f"recipe:name:{normalized_name}"


def key_id(recipe_id: str) -> str:
    return f"recipe:id:{recipe_id}"


# ---------------------------------------------------------------------------
# Cache writers
# ---------------------------------------------------------------------------

async def cache_recipe(record: RecipeRecord) -> None:
    if not record.url_hash:
        return
    try:
        r = get_redis()
        payload = record.model_dump_json()
        ttl = settings.redis_ttl_recipe
        async with r.pipeline(transaction=False) as pipe:
            pipe.set(key_url(record.url_hash), payload, ex=ttl)
            pipe.set(key_id(record.id), payload, ex=ttl)
            await pipe.execute()
    except Exception as exc:
        logger.warning("Redis cache_recipe failed: %s", exc)


async def cache_alias(normalized_name: str, recipe_id: str) -> None:
    try:
        r = get_redis()
        await r.set(key_name(normalized_name), recipe_id, ex=settings.redis_ttl_recipe)
    except Exception as exc:
        logger.warning("Redis cache_alias failed: %s", exc)


async def invalidate_recipe(recipe_id: str, url_hash: str) -> None:
    try:
        r = get_redis()
        async with r.pipeline(transaction=False) as pipe:
            pipe.delete(key_id(recipe_id))
            pipe.delete(key_url(url_hash))
            await pipe.execute()
    except Exception as exc:
        logger.warning("Redis invalidate_recipe failed: %s", exc)


# ---------------------------------------------------------------------------
# Cache readers  (all return None on miss or error)
# ---------------------------------------------------------------------------

async def get_recipe_by_url_hash(url_hash: str) -> RecipeRecord | None:
    try:
        raw = await get_redis().get(key_url(url_hash))
        return RecipeRecord.model_validate_json(raw) if raw else None
    except Exception as exc:
        logger.warning("Redis get_recipe_by_url_hash failed: %s", exc)
        return None


async def get_recipe_by_id(recipe_id: str) -> RecipeRecord | None:
    try:
        raw = await get_redis().get(key_id(recipe_id))
        return RecipeRecord.model_validate_json(raw) if raw else None
    except Exception as exc:
        logger.warning("Redis get_recipe_by_id failed: %s", exc)
        return None


async def get_recipe_id_by_name(normalized_name: str) -> str | None:
    try:
        return await get_redis().get(key_name(normalized_name))
    except Exception as exc:
        logger.warning("Redis get_recipe_id_by_name failed: %s", exc)
        return None
