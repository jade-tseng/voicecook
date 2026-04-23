"""Integration tests against the real dockerized Redis (DB 1)."""
import os
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError

import app.db.redis as redis_mod
from app.config import settings
from app.models.recipe import Ingredient, Instruction, RecipeRecord

# Use DB 1 so tests never touch the application DB 0
_BASE_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_TEST_URL = _BASE_URL.rsplit("/", 1)[0] + "/1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def redis(monkeypatch):
    """Real Redis connection on DB 1; flushes before and after each test."""
    client = aioredis.from_url(_TEST_URL, decode_responses=True)
    await client.flushdb()
    monkeypatch.setattr(redis_mod, "_redis", client)
    yield client
    await client.flushdb()
    await client.aclose()
    monkeypatch.setattr(redis_mod, "_redis", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    recipe_id: str = "11111111-1111-1111-1111-111111111111",
    url_hash: str = "abc123",
    title: str = "Chicken Soup",
) -> RecipeRecord:
    return RecipeRecord(
        id=recipe_id,
        url_hash=url_hash,
        title=title,
        source_url="https://example.com/chicken-soup",
        ingredients=[Ingredient(name="chicken", quantity="500", unit="g")],
        instructions=[Instruction(step=1, text="Boil the chicken.")],
        parser_version="v1",
    )


# ---------------------------------------------------------------------------
# Key builders (pure unit tests — no Redis needed)
# ---------------------------------------------------------------------------

def test_key_url():
    assert redis_mod.key_url("abc") == "recipe:url:abc"


def test_key_name():
    assert redis_mod.key_name("chicken-soup") == "recipe:name:chicken-soup"


def test_key_id():
    assert redis_mod.key_id("uuid-123") == "recipe:id:uuid-123"


# ---------------------------------------------------------------------------
# cache_recipe roundtrips
# ---------------------------------------------------------------------------

async def test_cache_recipe_then_get_by_url_hash(redis):
    record = _make_record()
    await redis_mod.cache_recipe(record)

    fetched = await redis_mod.get_recipe_by_url_hash(record.url_hash)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.title == record.title
    assert fetched.ingredients[0].name == "chicken"
    assert fetched.instructions[0].step == 1


async def test_cache_recipe_then_get_by_id(redis):
    record = _make_record()
    await redis_mod.cache_recipe(record)

    fetched = await redis_mod.get_recipe_by_id(record.id)
    assert fetched is not None
    assert fetched.url_hash == record.url_hash


async def test_cache_recipe_writes_both_keys(redis):
    record = _make_record()
    await redis_mod.cache_recipe(record)

    assert await redis.exists(redis_mod.key_url(record.url_hash)) == 1
    assert await redis.exists(redis_mod.key_id(record.id)) == 1


# ---------------------------------------------------------------------------
# cache_alias roundtrip
# ---------------------------------------------------------------------------

async def test_cache_alias_then_get_by_name(redis):
    record = _make_record()
    await redis_mod.cache_alias("chicken-soup", record.id)

    fetched_id = await redis_mod.get_recipe_id_by_name("chicken-soup")
    assert fetched_id == record.id


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------

async def test_cache_recipe_ttl_set(redis):
    record = _make_record()
    await redis_mod.cache_recipe(record)

    ttl_url = await redis.ttl(redis_mod.key_url(record.url_hash))
    ttl_id = await redis.ttl(redis_mod.key_id(record.id))
    assert 0 < ttl_url <= settings.redis_ttl_recipe
    assert 0 < ttl_id <= settings.redis_ttl_recipe


async def test_cache_alias_ttl_set(redis):
    await redis_mod.cache_alias("chicken-soup", "some-uuid")
    ttl = await redis.ttl(redis_mod.key_name("chicken-soup"))
    assert 0 < ttl <= settings.redis_ttl_recipe


# ---------------------------------------------------------------------------
# Miss behaviour
# ---------------------------------------------------------------------------

async def test_get_recipe_by_url_hash_miss(redis):
    assert await redis_mod.get_recipe_by_url_hash("no-such-hash") is None


async def test_get_recipe_by_id_miss(redis):
    assert await redis_mod.get_recipe_by_id("no-such-id") is None


async def test_get_recipe_id_by_name_miss(redis):
    assert await redis_mod.get_recipe_id_by_name("no-such-name") is None


# ---------------------------------------------------------------------------
# invalidate_recipe
# ---------------------------------------------------------------------------

async def test_invalidate_recipe_removes_both_keys(redis):
    record = _make_record()
    await redis_mod.cache_recipe(record)
    assert await redis.exists(redis_mod.key_url(record.url_hash)) == 1
    assert await redis.exists(redis_mod.key_id(record.id)) == 1

    await redis_mod.invalidate_recipe(record.id, record.url_hash)
    assert await redis.exists(redis_mod.key_url(record.url_hash)) == 0
    assert await redis.exists(redis_mod.key_id(record.id)) == 0


# ---------------------------------------------------------------------------
# Error resilience — getters must return None, not raise
# ---------------------------------------------------------------------------

async def test_get_recipe_by_url_hash_returns_none_on_connection_error(monkeypatch):
    mock = AsyncMock()
    mock.get.side_effect = RedisConnectionError("refused")
    monkeypatch.setattr(redis_mod, "_redis", mock)

    assert await redis_mod.get_recipe_by_url_hash("any") is None


async def test_get_recipe_by_id_returns_none_on_connection_error(monkeypatch):
    mock = AsyncMock()
    mock.get.side_effect = RedisConnectionError("refused")
    monkeypatch.setattr(redis_mod, "_redis", mock)

    assert await redis_mod.get_recipe_by_id("any") is None


async def test_get_recipe_id_by_name_returns_none_on_connection_error(monkeypatch):
    mock = AsyncMock()
    mock.get.side_effect = RedisConnectionError("refused")
    monkeypatch.setattr(redis_mod, "_redis", mock)

    assert await redis_mod.get_recipe_id_by_name("any") is None
