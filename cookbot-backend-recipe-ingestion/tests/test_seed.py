"""Tests for scripts/seed.py — no real DB or HTTP calls."""
import asyncio
from unittest.mock import AsyncMock

import pytest

import app.db.postgres as pg_mod
import scripts.seed as seed_mod
from app.ingestion.parser import ExtractError, FetchError
from app.models.recipe import Ingredient, Instruction, RecipeRecord

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _fake_record(title: str = "Fake Recipe") -> RecipeRecord:
    return RecipeRecord(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        title=title,
        source_url="https://example.com/recipe",
        url_hash="a" * 64,
        ingredients=[Ingredient(name="ingredient")],
        instructions=[Instruction(step=1, text="Cook it.")],
        parser_version="d1",
    )


@pytest.fixture
def no_existing(monkeypatch):
    """Patch postgres.get_recipe_by_url_hash to always return None (URL not in DB)."""
    monkeypatch.setattr(pg_mod, "get_recipe_by_url_hash", AsyncMock(return_value=None))


@pytest.fixture
def all_existing(monkeypatch):
    """Patch postgres.get_recipe_by_url_hash to always return a record (already in DB)."""
    monkeypatch.setattr(pg_mod, "get_recipe_by_url_hash", AsyncMock(return_value=_fake_record()))


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------

async def test_summary_counts_success_and_failures(no_existing, monkeypatch):
    """3 successes, 1 FetchError, 1 ExtractError → correct stat buckets."""
    urls = [
        "https://example.com/recipe1",
        "https://example.com/recipe2",
        "https://example.com/recipe3",
        "https://example.com/fetch-error",
        "https://example.com/extract-error",
    ]

    async def mock_resolve(url):
        if "fetch-error" in url:
            raise FetchError("timeout")
        if "extract-error" in url:
            raise ExtractError("no recipe schema")
        return _fake_record()

    monkeypatch.setattr(seed_mod, "resolve_recipe", mock_resolve)

    stats = await seed_mod.run_seed(urls, concurrency=5)

    assert stats["seeded"] == 3
    assert stats["skipped"] == 0
    assert stats["failed"] == 2
    assert stats["errors"]["FetchError"] == 1
    assert stats["errors"]["ExtractError"] == 1


async def test_skipped_counts_urls_already_in_db(all_existing, monkeypatch):
    """URLs already in DB are counted as skipped; resolve_recipe never called."""
    resolve_mock = AsyncMock(return_value=_fake_record())
    monkeypatch.setattr(seed_mod, "resolve_recipe", resolve_mock)

    urls = [
        "https://example.com/recipe1",
        "https://example.com/recipe2",
    ]
    stats = await seed_mod.run_seed(urls, concurrency=2)

    assert stats["seeded"] == 0
    assert stats["skipped"] == 2
    assert stats["failed"] == 0
    resolve_mock.assert_not_called()


async def test_blank_and_comment_lines_ignored(no_existing, monkeypatch):
    """Blank lines and # comments don't count toward any stat bucket."""
    resolve_mock = AsyncMock(return_value=_fake_record())
    monkeypatch.setattr(seed_mod, "resolve_recipe", resolve_mock)

    urls = [
        "",
        "# this is a comment",
        "  ",
        "https://example.com/real-recipe",
        "",
    ]
    stats = await seed_mod.run_seed(urls, concurrency=2)

    assert stats["seeded"] == 1
    assert resolve_mock.call_count == 1


# ---------------------------------------------------------------------------
# Concurrency cap
# ---------------------------------------------------------------------------

async def test_concurrency_cap_respected(no_existing, monkeypatch):
    """Max concurrent calls to resolve_recipe never exceeds --concurrency."""
    concurrency = 3
    state = {"current": 0, "max_seen": 0}

    async def tracking_resolve(url):
        state["current"] += 1
        state["max_seen"] = max(state["max_seen"], state["current"])
        await asyncio.sleep(0.02)   # hold the semaphore slot briefly
        state["current"] -= 1
        return _fake_record()

    monkeypatch.setattr(seed_mod, "resolve_recipe", tracking_resolve)

    urls = [f"https://example.com/recipe{i}" for i in range(12)]
    await seed_mod.run_seed(urls, concurrency=concurrency)

    assert state["max_seen"] <= concurrency, (
        f"max concurrent was {state['max_seen']}, expected ≤ {concurrency}"
    )


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------

async def test_limit_stops_after_n_successes(no_existing, monkeypatch):
    """With limit=3 and 10 URLs, exactly 3 are seeded and resolve stops early."""
    resolve_mock = AsyncMock(return_value=_fake_record())
    monkeypatch.setattr(seed_mod, "resolve_recipe", resolve_mock)

    urls = [f"https://example.com/recipe{i}" for i in range(10)]
    stats = await seed_mod.run_seed(urls, concurrency=1, limit=3)

    assert stats["seeded"] == 3
    # With concurrency=1, no over-shoot: exactly 3 calls
    assert resolve_mock.call_count == 3


async def test_limit_with_concurrency_does_not_exceed_much(no_existing, monkeypatch):
    """With concurrency > 1, seeded may slightly exceed limit by at most
    (concurrency - 1) due to in-flight tasks, but stops promptly."""
    concurrency = 4
    limit = 5
    resolve_mock = AsyncMock(return_value=_fake_record())
    monkeypatch.setattr(seed_mod, "resolve_recipe", resolve_mock)

    urls = [f"https://example.com/recipe{i}" for i in range(20)]
    stats = await seed_mod.run_seed(urls, concurrency=concurrency, limit=limit)

    # Seeded is exactly limit because stop is checked INSIDE the semaphore
    # before calling resolve_recipe for subsequent tasks
    assert stats["seeded"] == limit


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

async def test_dry_run_calls_neither_resolve_nor_db(monkeypatch):
    """--dry-run: neither resolve_recipe nor DB is touched."""
    resolve_mock = AsyncMock()
    db_mock = AsyncMock()
    monkeypatch.setattr(seed_mod, "resolve_recipe", resolve_mock)
    monkeypatch.setattr(pg_mod, "get_recipe_by_url_hash", db_mock)

    urls = [
        "https://example.com/recipe1",
        "https://example.com/recipe2",
        "# a comment",
        "",
    ]
    stats = await seed_mod.run_seed(urls, dry_run=True)

    resolve_mock.assert_not_called()
    db_mock.assert_not_called()
    # Dry-run doesn't update stats buckets
    assert stats["seeded"] == 0
    assert stats["skipped"] == 0
    assert stats["failed"] == 0


async def test_dry_run_handles_non_url_input(monkeypatch, capsys):
    """Non-URL lines in dry-run are classified and printed, not errored."""
    monkeypatch.setattr(seed_mod, "resolve_recipe", AsyncMock())
    monkeypatch.setattr(pg_mod, "get_recipe_by_url_hash", AsyncMock())

    await seed_mod.run_seed(["chicken tikka masala"], dry_run=True)

    out = capsys.readouterr().out
    assert "not a URL" in out
