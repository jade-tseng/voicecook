"""URL → RecipeBase parser.

Primary path:  recipe-scrapers (wild_mode=True)
Fallback path: extruct JSON-LD

TODO: add Playwright/JS-rendered fallback for SPAs that need a real browser.
TODO: add LLM extraction fallback when both structured paths return nothing.
"""
import logging
import re
from typing import Any

import extruct
import httpx
import recipe_scrapers
from recipe_scrapers._exceptions import (
    ElementNotFoundInHtml,
    FieldNotProvidedByWebsiteException,
    NoSchemaFoundInWildMode,
    SchemaOrgException,
    WebsiteNotImplementedError,
)

from app.ingestion.input import normalize_url
from app.models.recipe import Ingredient, Instruction, RecipeBase

logger = logging.getLogger(__name__)

PARSER_VERSION = "d1"

_USER_AGENT = "CookBot/0.1 (+https://cookbot.example)"

# Ingredients are stored as raw strings in Ingredient.name;
# quantity/unit/notes remain None until the NER layer (deferred).
# Instructions are stored as Instruction(step=N, text=raw_text).

_SCRAPER_ERRORS = (
    NoSchemaFoundInWildMode,
    SchemaOrgException,
    WebsiteNotImplementedError,
    FieldNotProvidedByWebsiteException,
    ElementNotFoundInHtml,
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """Base for all parser failures."""


class FetchError(ParseError):
    """Network or HTTP-level failure."""


class ExtractError(ParseError):
    """Got HTML but could not extract a recipe."""


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

async def fetch_html(url: str) -> str:
    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as exc:
            raise FetchError(
                f"HTTP {exc.response.status_code} fetching {url}"
            ) from exc
        except httpx.RequestError as exc:
            raise FetchError(f"Network error fetching {url}: {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso_duration(raw: str | None) -> int | None:
    """Parse ISO 8601 duration string to total minutes.

    Handles PT{H}H{M}M, PT{H}H, PT{M}M. Returns None on unparseable input.
    """
    if not raw:
        return None
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw.strip().upper())
    if not m or not any(m.groups()):
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    return hours * 60 + minutes


def _parse_servings(raw: Any) -> int | None:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        m = re.search(r"\d+", raw)
        return int(m.group()) if m else None
    return None


def _extract_image(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw or None
    if isinstance(raw, list):
        return _extract_image(raw[0]) if raw else None
    if isinstance(raw, dict):
        return raw.get("url") or raw.get("@id") or None
    return None


def _clean_nutrition(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    cleaned = {k: v for k, v in raw.items() if not k.startswith("@")}
    return cleaned or None


# ---------------------------------------------------------------------------
# Primary path: recipe-scrapers
# ---------------------------------------------------------------------------

def _try_scrapers(html: str, url: str) -> RecipeBase:
    scraper = recipe_scrapers.scrape_html(html, org_url=url, supported_only=False)

    try:
        raw_ingredients = scraper.ingredients()
    except Exception:
        raw_ingredients = []

    try:
        raw_steps = scraper.instructions_list()
    except Exception:
        raw_steps = []

    try:
        total_time = scraper.total_time()
    except Exception:
        total_time = None

    try:
        servings = _parse_servings(scraper.yields())
    except Exception:
        servings = None

    try:
        image = scraper.image()
    except Exception:
        image = None

    try:
        nutrition = _clean_nutrition(scraper.nutrients())
    except Exception:
        nutrition = None

    ingredients = [
        Ingredient(name=s.strip())
        for s in raw_ingredients
        if isinstance(s, str) and s.strip()
    ]
    instructions = [
        Instruction(step=i + 1, text=text.strip())
        for i, text in enumerate(raw_steps)
        if isinstance(text, str) and text.strip()
    ]

    return RecipeBase(
        title=scraper.title(),
        source_url=url,
        ingredients=ingredients,
        instructions=instructions,
        total_time_min=total_time,
        servings=servings,
        image_url=image,
        nutrition=nutrition,
    )


# ---------------------------------------------------------------------------
# Fallback path: extruct JSON-LD
# ---------------------------------------------------------------------------

def _try_extruct(html: str, url: str) -> RecipeBase:
    data = extruct.extract(html, base_url=url, syntaxes=["json-ld"])

    recipe_obj: dict | None = None
    for item in data.get("json-ld", []):
        types = item.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if "Recipe" in types:
            recipe_obj = item
            break

    if recipe_obj is None:
        raise ExtractError(f"No Recipe object found in JSON-LD at {url}")

    title = recipe_obj.get("name") or ""

    raw_ingredients = recipe_obj.get("recipeIngredient", [])
    ingredients = [
        Ingredient(name=s.strip())
        for s in raw_ingredients
        if isinstance(s, str) and s.strip()
    ]

    raw_instructions = recipe_obj.get("recipeInstructions", [])
    instructions: list[Instruction] = []
    step = 1

    if isinstance(raw_instructions, str):
        for line in raw_instructions.splitlines():
            line = line.strip()
            if line:
                instructions.append(Instruction(step=step, text=line))
                step += 1
    elif isinstance(raw_instructions, list):
        for item in raw_instructions:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = item.get("text", "").strip()
            else:
                continue
            if text:
                instructions.append(Instruction(step=step, text=text))
                step += 1

    return RecipeBase(
        title=title,
        source_url=url,
        ingredients=ingredients,
        instructions=instructions,
        total_time_min=_parse_iso_duration(recipe_obj.get("totalTime")),
        servings=_parse_servings(recipe_obj.get("recipeYield")),
        image_url=_extract_image(recipe_obj.get("image")),
        nutrition=_clean_nutrition(recipe_obj.get("nutrition")),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_url(url: str) -> tuple[RecipeBase, str]:
    """Fetch and parse a recipe URL. Returns (RecipeBase, raw_html).

    Normalizes the URL first, tries recipe-scrapers, falls back to extruct
    JSON-LD, raises ExtractError if both fail or yield no ingredients/instructions.
    """
    canonical_url, _ = normalize_url(url)
    html = await fetch_html(canonical_url)

    # --- Primary ---
    recipe: RecipeBase | None = None
    try:
        recipe = _try_scrapers(html, canonical_url)
        if not recipe.ingredients or not recipe.instructions:
            logger.debug("recipe-scrapers returned empty result for %s, trying extruct", canonical_url)
            recipe = None
    except _SCRAPER_ERRORS as exc:
        logger.debug("recipe-scrapers raised %s for %s: %s", type(exc).__name__, canonical_url, exc)
    except Exception as exc:
        logger.warning("recipe-scrapers unexpected error for %s: %s", canonical_url, exc)

    if recipe is not None:
        return recipe, html

    # --- Fallback ---
    try:
        recipe = _try_extruct(html, canonical_url)
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractError(f"extruct failed for {canonical_url}: {exc}") from exc

    if not recipe.ingredients or not recipe.instructions:
        raise ExtractError(
            f"Extracted recipe from {canonical_url} has no ingredients or instructions"
        )

    return recipe, html
