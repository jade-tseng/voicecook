"""Parser tests — no real HTTP calls."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import recipe_scrapers
from recipe_scrapers._exceptions import NoSchemaFoundInWildMode

from app.ingestion.parser import (
    ExtractError,
    FetchError,
    _extract_image,
    _parse_iso_duration,
    _parse_servings,
    parse_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def load_fixture():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text()
    return _load


@pytest.fixture
def mock_fetch(monkeypatch):
    """Return a factory; call it with HTML to patch fetch_html."""
    def _factory(html: str):
        monkeypatch.setattr(
            "app.ingestion.parser.fetch_html",
            AsyncMock(return_value=html),
        )
    return _factory


@pytest.fixture
def mock_scrapers_raise(monkeypatch):
    """Patch recipe_scrapers.scrape_html to raise NoSchemaFoundInWildMode."""
    monkeypatch.setattr(
        recipe_scrapers,
        "scrape_html",
        MagicMock(side_effect=NoSchemaFoundInWildMode("no schema")),
    )


@pytest.fixture
def mock_scrapers_empty_ingredients(monkeypatch):
    """Patch recipe_scrapers.scrape_html to return a scraper with no ingredients."""
    fake = MagicMock()
    fake.title.return_value = "Fake Title"
    fake.ingredients.return_value = []
    fake.instructions_list.return_value = ["Step one"]
    fake.total_time.return_value = 20
    fake.yields.return_value = "2"
    fake.image.return_value = None
    fake.nutrients.return_value = {}
    monkeypatch.setattr(recipe_scrapers, "scrape_html", MagicMock(return_value=fake))


# ---------------------------------------------------------------------------
# _parse_iso_duration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("PT45M",   45),
    ("PT1H",    60),
    ("PT1H30M", 90),
    ("PT0M",     0),
    ("pt2h15m", 135),   # lowercase
    ("",        None),
    (None,      None),
    ("invalid", None),
    ("P1D",     None),  # days not supported
])
def test_parse_iso_duration(raw, expected):
    assert _parse_iso_duration(raw) == expected


# ---------------------------------------------------------------------------
# _parse_servings
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("4 servings", 4),
    ("Serves 4",   4),
    ("4",          4),
    (4,            4),
    ("Makes 12 cookies", 12),
    ("",           None),
    (None,         None),
    ("no digits",  None),
])
def test_parse_servings(raw, expected):
    assert _parse_servings(raw) == expected


# ---------------------------------------------------------------------------
# _extract_image
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://example.com/img.jpg",                         "https://example.com/img.jpg"),
    (["https://example.com/a.jpg", "https://example.com/b.jpg"], "https://example.com/a.jpg"),
    ({"url": "https://example.com/img.jpg"},                "https://example.com/img.jpg"),
    ({"@type": "ImageObject", "url": "https://example.com/img.jpg"}, "https://example.com/img.jpg"),
    (None,  None),
    ([],    None),
    ("",    None),
])
def test_extract_image(raw, expected):
    assert _extract_image(raw) == expected


# ---------------------------------------------------------------------------
# parse_url — primary path (recipe-scrapers)
# ---------------------------------------------------------------------------

async def test_parse_url_primary_path(load_fixture, mock_fetch):
    """recipe-scrapers successfully extracts from allrecipes_sample.html."""
    mock_fetch(load_fixture("allrecipes_sample.html"))

    recipe, raw_html = await parse_url("https://www.allrecipes.com/recipe/12345/carbonara")

    assert recipe.title == "Classic Spaghetti Carbonara"
    assert len(recipe.ingredients) == 5
    assert all(ing.name for ing in recipe.ingredients)
    # NER is deferred — quantity/unit/notes are None
    assert all(ing.quantity is None for ing in recipe.ingredients)
    assert len(recipe.instructions) == 4
    assert recipe.instructions[0].step == 1
    assert recipe.instructions[3].step == 4
    assert recipe.total_time_min == 30
    assert recipe.servings == 4
    assert recipe.image_url == "https://example.com/carbonara.jpg"
    assert recipe.source_url is not None
    assert len(raw_html) > 0


# ---------------------------------------------------------------------------
# parse_url — fallback: scraper raises → extruct takes over
# ---------------------------------------------------------------------------

async def test_parse_url_falls_back_when_scraper_raises(
    load_fixture, mock_fetch, mock_scrapers_raise
):
    """When recipe-scrapers raises, extruct JSON-LD is tried."""
    mock_fetch(load_fixture("minimal_jsonld.html"))

    recipe, _ = await parse_url("https://example.com/shrimp")

    assert recipe.title == "Lemon Garlic Shrimp"
    assert len(recipe.ingredients) == 6
    assert len(recipe.instructions) == 4
    assert recipe.total_time_min == 15
    assert recipe.servings == 2


async def test_parse_url_falls_back_when_scraper_returns_empty_ingredients(
    load_fixture, mock_fetch, mock_scrapers_empty_ingredients
):
    """When recipe-scrapers returns empty ingredients, extruct is tried."""
    mock_fetch(load_fixture("minimal_jsonld.html"))

    recipe, _ = await parse_url("https://example.com/shrimp")

    # extruct should find the real ingredients
    assert len(recipe.ingredients) > 0
    assert recipe.title == "Lemon Garlic Shrimp"


# ---------------------------------------------------------------------------
# parse_url — HowToStep objects and multi-type @type
# ---------------------------------------------------------------------------

async def test_parse_url_howto_step_instructions_via_extruct(
    load_fixture, mock_fetch, mock_scrapers_raise
):
    """extruct correctly extracts HowToStep objects from @type list."""
    mock_fetch(load_fixture("howto_step_objects.html"))

    recipe, _ = await parse_url("https://example.com/tacos")

    assert recipe.title == "Beef Tacos"
    assert len(recipe.instructions) == 4
    # Steps are numbered sequentially
    assert [i.step for i in recipe.instructions] == [1, 2, 3, 4]
    assert "ground beef" in recipe.instructions[0].text.lower()
    # image is a list → extruct returns first element
    assert recipe.image_url == "https://example.com/tacos-16x9.jpg"
    # recipeYield is "4" (no units) → servings = 4
    assert recipe.servings == 4


# ---------------------------------------------------------------------------
# parse_url — no recipe schema → ExtractError
# ---------------------------------------------------------------------------

async def test_parse_url_no_recipe_raises_extract_error(load_fixture, mock_fetch):
    """Both paths fail for a plain non-recipe page → ExtractError raised."""
    mock_fetch(load_fixture("no_recipe.html"))

    with pytest.raises(ExtractError):
        await parse_url("https://example.com/about")


# ---------------------------------------------------------------------------
# parse_url — fetch failure → FetchError propagates
# ---------------------------------------------------------------------------

async def test_parse_url_fetch_error_propagates(monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.parser.fetch_html",
        AsyncMock(side_effect=FetchError("HTTP 404 fetching ...")),
    )
    with pytest.raises(FetchError):
        await parse_url("https://example.com/missing")


# ---------------------------------------------------------------------------
# Ingredient model choice (documented assertion)
# ---------------------------------------------------------------------------

async def test_ingredients_stored_as_raw_name(load_fixture, mock_fetch):
    """Raw ingredient strings go into Ingredient.name; NER fields are None."""
    mock_fetch(load_fixture("allrecipes_sample.html"))
    recipe, _ = await parse_url("https://www.allrecipes.com/recipe/12345/carbonara")

    first = recipe.ingredients[0]
    assert first.name == "400g spaghetti"
    assert first.quantity is None
    assert first.unit is None
    assert first.notes is None
