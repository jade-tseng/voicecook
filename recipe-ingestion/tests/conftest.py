"""Shared pytest fixtures for the CookBot test suite."""
import json
import os

import asyncpg
import pytest
import redis.asyncio as aioredis

from app.db.migrate import run_migrations
from app.db.postgres import close_pool, init_pool
from app.db.redis import close_redis, init_redis

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://cookbot:cookbot@localhost:5432/cookbot"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


# ---------------------------------------------------------------------------
# Postgres: per-test connection with clean tables
# ---------------------------------------------------------------------------

@pytest.fixture
async def pg():
    """Real asyncpg connection; runs migrations and truncates tables around each test."""
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json",  encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await run_migrations(conn)
    await conn.execute("TRUNCATE recipe_name_aliases, recipes CASCADE")
    yield conn
    await conn.execute("TRUNCATE recipe_name_aliases, recipes CASCADE")
    await conn.close()


# ---------------------------------------------------------------------------
# Application lifecycle: global pool + Redis for orchestrator tests
# ---------------------------------------------------------------------------

@pytest.fixture
async def app_lifecycle(pg):
    """Initialize the global asyncpg pool and Redis client for a single test.

    Depends on `pg` so tables are already clean before the pool opens.
    Flushes Redis DB 0 before and after.
    """
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    await r.flushdb()
    await r.aclose()

    await init_pool()
    await init_redis()
    yield

    await close_redis()
    await close_pool()

    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    await r.flushdb()
    await r.aclose()


# ---------------------------------------------------------------------------
# HTTP test client
# ---------------------------------------------------------------------------

@pytest.fixture
async def http_client(app_lifecycle):
    """httpx AsyncClient wired to the FastAPI app.

    Depends on `app_lifecycle` so the global pool and Redis are already
    initialized before requests hit the app.  httpx.ASGITransport does not
    trigger FastAPI's lifespan startup events, so we must wire lifecycle
    ourselves via the app_lifecycle fixture.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
