"""Resolve a dish name to either an existing DB recipe or a URL to parse.

Resolution order (stops at first hit):
  1. Alias exact match  → recipe_id, match_type="alias_exact"
  2. Postgres FTS       → recipe_id, match_type="fts"   (rank >= FTS_THRESHOLD)
  3. Web search stub    → source_url, match_type="web_search"

The orchestrator (Section F) is responsible for running the parser when
source_url is returned, and for writing Redis / Postgres afterwards.
"""
import logging

from app.db import postgres
from app.ingestion.input import normalize_name
from app.models.recipe import ResolveResult

logger = logging.getLogger(__name__)

FTS_THRESHOLD: float = 0.05


# ---------------------------------------------------------------------------
# Web search stub — real implementation added when provider is chosen
# ---------------------------------------------------------------------------

async def web_search(query: str) -> str | None:  # noqa: RUF029
    """Return the top recipe URL for *query*, or None.

    Currently raises NotImplementedError; the orchestrator treats this as
    a cache miss and returns None from resolve_name.
    """
    raise NotImplementedError("web search not configured")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def resolve_name(
    original_name: str,
    conn=None,
) -> ResolveResult | None:
    """Resolve a dish name to a ResolveResult, or None if all tiers miss."""
    normalized = normalize_name(original_name)

    # --- Tier 1: alias exact match ---
    recipe_id = await postgres.get_alias(normalized, conn=conn)
    if recipe_id:
        logger.debug("alias hit for %r → %s", normalized, recipe_id)
        return ResolveResult(
            normalized_name=normalized,
            match_type="alias_exact",
            recipe_id=recipe_id,
        )

    # --- Tier 2: Postgres FTS ---
    hits = await postgres.search_recipes_by_name(original_name, limit=5, conn=conn)
    if hits:
        top_record, top_rank = hits[0]
        if top_rank >= FTS_THRESHOLD:
            logger.debug("FTS hit for %r → %s (rank=%.4f)", original_name, top_record.id, top_rank)
            return ResolveResult(
                normalized_name=normalized,
                match_type="fts",
                recipe_id=top_record.id,
            )
        logger.debug("FTS top rank %.4f below threshold %.2f for %r", top_rank, FTS_THRESHOLD, original_name)

    # --- Tier 3: web search ---
    try:
        url = await web_search(original_name)
    except NotImplementedError:
        logger.info("web search not configured — resolve_name returning None for %r", original_name)
        return None

    if url:
        logger.debug("web search hit for %r → %s", original_name, url)
        return ResolveResult(
            normalized_name=normalized,
            match_type="web_search",
            source_url=url,
        )

    return None
