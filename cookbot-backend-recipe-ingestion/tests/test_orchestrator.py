"""Orchestrator integration tests — real Postgres + real Redis.

Mock scope: ONLY parser.parse_url and resolver.web_search.
All other I/O (DB reads/writes, Redis reads/writes) is real.

Fixtures from conftest.py:
  pg            — clean asyncpg connection (tables truncated)
  app_lifecycle — initializes global pool + Redis; depends on pg
  http_client   — httpx AsyncClient wired to the FastAPI app; depends on app_lifecycle
"""
from unittest.mock import AsyncMock

import pytest

import app.ingestion.parser as parser_mod
import app.ingestion.resolver as resolver_mod
from app.db import postgres, redis as redis_mod
from app.ingestion.input import normalize_name, normalize_url
from app.ingestion.orchestrator import RecipeNotFound, resolve_recipe
from app.models.recipe import Ingredient, Instruction, RecipeBase, RecipeRecord

# ---------------------------------------------------------------------------
# URL constants + real hashes (must match what normalize_url produces)
# ---------------------------------------------------------------------------

_URL_A = "https://example.com/pasta"
_URL_B = "https://example.com/tacos"
_, _HASH_A = normalize_url(_URL_A)
_, _HASH_B = normalize_url(_URL_B)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_base(
    title: str = "Test Pasta",
    source_url: str = _URL_A,
) -> RecipeBase:
    return RecipeBase(
        title=title,
        source_url=source_url,
        ingredients=[Ingredient(name="pasta"), Ingredient(name="olive oil")],
        instructions=[
            Instruction(step=1, text="Boil salted water."),
            Instruction(step=2, text="Cook pasta al dente and serve."),
        ],
        total_time_min=45,
        servings=4,
        cuisine="italian",
        difficulty="medium",
        image_url="https://example.com/img.jpg",
        nutrition={"calories": "500", "fat": "20g", "protein": "30g"},
    )


def _make_record(
    title: str = "Test Pasta",
    recipe_id: str = "11111111-1111-1111-1111-111111111111",
    url_hash: str = _HASH_A,
    source_url: str = _URL_A,
) -> RecipeRecord:
    return RecipeRecord(
        id=recipe_id,
        title=title,
        source_url=source_url,
        url_hash=url_hash,
        ingredients=[Ingredient(name="pasta"), Ingredient(name="olive oil")],
        instructions=[
            Instruction(step=1, text="Boil salted water."),
            Instruction(step=2, text="Cook pasta al dente and serve."),
        ],
        total_time_min=45,
        servings=4,
        cuisine="italian",
        difficulty="medium",
        image_url="https://example.com/img.jpg",
        nutrition={"calories": "500", "fat": "20g", "protein": "30g"},
        parser_version="v1",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_parse_url(monkeypatch):
    """Always patches parser.parse_url with a Mock (default: AssertionError).

    The returned configure() lets individual tests set a return value or a
    specific exception — call it only when the test *expects* the parser to run.

    Tests that should NOT hit the parser just take this fixture and never call
    configure; if the parser is called anyway the AssertionError surfaces clearly.
    """
    mock = AsyncMock(side_effect=AssertionError("parse_url must not be called in this test"))
    monkeypatch.setattr(parser_mod, "parse_url", mock)

    def configure(recipe: RecipeBase | None = None, html: str = "<html/>", exc=None):
        if exc is not None:
            mock.side_effect = exc
            mock.return_value = None
        else:
            mock.side_effect = None
            mock.return_value = (recipe or _make_base(), html)

    return configure


@pytest.fixture
def mock_web_search(monkeypatch):
    """Patch resolver.web_search — call with the URL it should return."""
    def configure(url: str | None = None):
        monkeypatch.setattr(
            resolver_mod, "web_search", AsyncMock(return_value=url)
        )
    return configure


# ===========================================================================
# URL path
# ===========================================================================

async def test_url_redis_hit(app_lifecycle, mock_parse_url):
    """URL already in Redis → returned immediately; parser never called."""
    record = _make_record()
    await redis_mod.cache_recipe(record)

    result = await resolve_recipe(_URL_A)

    assert result.id == record.id
    assert result.title == "Test Pasta"
    parser_mod.parse_url.assert_not_called()


async def test_url_postgres_hit_warms_redis(app_lifecycle, pg, mock_parse_url):
    """URL in Postgres but not Redis → returned; Redis warmed afterwards."""
    await postgres.insert_recipe(_make_base(), _HASH_A, "<html/>", "v1", conn=pg)

    result = await resolve_recipe(_URL_A)

    assert result.title == "Test Pasta"
    parser_mod.parse_url.assert_not_called()

    cached = await redis_mod.get_recipe_by_url_hash(_HASH_A)
    assert cached is not None
    assert cached.id == result.id


async def test_url_full_miss_calls_parser_and_persists(app_lifecycle, pg, mock_parse_url):
    """URL in neither cache → parser called; recipe written to Postgres + Redis."""
    mock_parse_url()  # configure to return _make_base() + "<html/>"

    result = await resolve_recipe(_URL_A)

    assert result.title == "Test Pasta"
    parser_mod.parse_url.assert_called_once()

    # Persisted to Postgres
    db_record = await postgres.get_recipe_by_url_hash(_HASH_A, conn=pg)
    assert db_record is not None

    # Warmed in Redis
    assert await redis_mod.get_recipe_by_url_hash(_HASH_A) is not None
    assert await redis_mod.get_recipe_by_id(result.id) is not None


async def test_url_fetch_error_propagates(app_lifecycle, mock_parse_url):
    """FetchError from parser propagates unchanged."""
    from app.ingestion.parser import FetchError
    mock_parse_url(exc=FetchError("timeout"))

    with pytest.raises(FetchError):
        await resolve_recipe(_URL_A)


# ===========================================================================
# Name path
# ===========================================================================

async def test_name_redis_full_hit(app_lifecycle, mock_parse_url):
    """Alias + body both in Redis → returned immediately; no DB call."""
    record = _make_record()
    norm = normalize_name("Test Pasta")
    await redis_mod.cache_recipe(record)
    await redis_mod.cache_alias(norm, record.id)

    result = await resolve_recipe("Test Pasta")

    assert result.id == record.id
    parser_mod.parse_url.assert_not_called()


async def test_name_redis_stale_alias_falls_through_to_postgres(
    app_lifecycle, pg, mock_parse_url
):
    """Redis alias pointer exists but body is missing → falls to resolver → FTS hit."""
    db_record = await postgres.insert_recipe(
        _make_base(title="Chicken Soup", source_url="https://example.com/chicken-soup"),
        _HASH_A, "<html/>", "v1", conn=pg,
    )
    norm = normalize_name("Chicken Soup")
    # Only the alias pointer in Redis; body NOT cached
    await redis_mod.cache_alias(norm, db_record.id)

    result = await resolve_recipe("Chicken Soup")

    assert result.id == db_record.id
    parser_mod.parse_url.assert_not_called()


async def test_name_fts_hit_warms_redis_and_upserts_alias(
    app_lifecycle, pg, mock_parse_url
):
    """FTS hit → recipe returned; Redis warmed; name alias cached in Redis."""
    db_record = await postgres.insert_recipe(
        _make_base(title="Chicken Tikka Masala", source_url="https://example.com/tikka"),
        _HASH_A, "<html/>", "v1", conn=pg,
    )

    result = await resolve_recipe("tikka masala")

    assert result.id == db_record.id
    parser_mod.parse_url.assert_not_called()

    # Redis body warmed
    assert await redis_mod.get_recipe_by_id(result.id) is not None

    # Redis alias written
    norm = normalize_name("tikka masala")
    cached_id = await redis_mod.get_recipe_id_by_name(norm)
    assert cached_id == result.id


async def test_name_web_search_parses_and_writes_alias(
    app_lifecycle, pg, mock_parse_url, mock_web_search
):
    """web_search returns URL → parser called; recipe + alias persisted everywhere."""
    mock_web_search(_URL_B)
    mock_parse_url(recipe=_make_base(title="Beef Tacos", source_url=_URL_B))

    result = await resolve_recipe("beef tacos")

    assert result.title == "Beef Tacos"
    parser_mod.parse_url.assert_called_once()

    # Postgres alias written
    norm = normalize_name("beef tacos")
    alias_recipe_id = await postgres.get_alias(norm, conn=pg)
    assert alias_recipe_id == result.id

    # Redis alias written
    cached_id = await redis_mod.get_recipe_id_by_name(norm)
    assert cached_id == result.id


async def test_name_all_miss_raises_recipe_not_found(app_lifecycle, mock_parse_url):
    """No alias, no FTS hit, web_search raises NotImplementedError → RecipeNotFound."""
    with pytest.raises(RecipeNotFound):
        await resolve_recipe("xkzqwerty flibbertigibbet zorblax")


# ===========================================================================
# Endpoint tests (HTTP)
# ===========================================================================

async def test_endpoint_resolve_url_200(http_client, pg, monkeypatch):
    """POST /recipes/resolve with a URL → 200 with RecipeRecord JSON shape."""
    monkeypatch.setattr(
        parser_mod, "parse_url",
        AsyncMock(return_value=(_make_base(), "<html/>")),
    )

    resp = await http_client.post("/recipes/resolve", json={"input": _URL_A})

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Test Pasta"
    assert "id" in body
    assert isinstance(body["ingredients"], list)
    assert isinstance(body["instructions"], list)


async def test_endpoint_resolve_fetch_error_502(http_client, monkeypatch):
    """Parser raises FetchError → 502."""
    from app.ingestion.parser import FetchError
    monkeypatch.setattr(
        parser_mod, "parse_url",
        AsyncMock(side_effect=FetchError("timeout")),
    )

    resp = await http_client.post("/recipes/resolve", json={"input": _URL_A})

    assert resp.status_code == 502
    assert resp.json()["detail"] == "could not fetch recipe url"


async def test_endpoint_resolve_not_found_404(http_client):
    """Name with no matches → 404."""
    resp = await http_client.post(
        "/recipes/resolve", json={"input": "xkzqwerty flibbertigibbet"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "no recipe found for input"


async def test_endpoint_empty_input_422(http_client):
    """Empty string violates min_length=1 → 422."""
    resp = await http_client.post("/recipes/resolve", json={"input": ""})
    assert resp.status_code == 422


# ===========================================================================
# Optional field round-trip
# ===========================================================================

async def test_optional_fields_survive_roundtrip(app_lifecycle, pg, mock_parse_url):
    """All optional RecipeBase fields make it through parse → DB insert → Redis → retrieval."""
    mock_parse_url()  # _make_base() now includes all optional fields

    result = await resolve_recipe(_URL_A)

    # Fields must survive Postgres insert
    assert result.total_time_min == 45
    assert result.servings == 4
    assert result.cuisine == "italian"
    assert result.difficulty == "medium"
    assert result.image_url == "https://example.com/img.jpg"
    assert result.nutrition == {"calories": "500", "fat": "20g", "protein": "30g"}
    assert len(result.ingredients) == 2
    assert len(result.instructions) == 2

    # Fields must also survive Redis cache → retrieval via url_hash
    cached = await redis_mod.get_recipe_by_url_hash(_HASH_A)
    assert cached is not None
    assert cached.total_time_min == 45
    assert cached.servings == 4
    assert cached.cuisine == "italian"
    assert cached.difficulty == "medium"
    assert cached.image_url == "https://example.com/img.jpg"
    assert cached.nutrition == {"calories": "500", "fat": "20g", "protein": "30g"}

    # And via id key
    cached_by_id = await redis_mod.get_recipe_by_id(result.id)
    assert cached_by_id is not None
    assert cached_by_id.nutrition == {"calories": "500", "fat": "20g", "protein": "30g"}
