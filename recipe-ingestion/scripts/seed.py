"""
Recipe URL seeder — populates the CookBot recipe database from a URL list.

Usage:
    python -m scripts.seed --urls seed_urls.example.txt [options]

Options:
    --urls          Path to newline-delimited file of recipe URLs (required)
    --concurrency   Max parallel parses (default: 10)
    --limit         Stop after N successful parses (default: no limit)
    --dry-run       Classify + normalize only; no HTTP fetches or DB writes
"""
import argparse
import asyncio
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

from app.db import postgres
from app.db.migrate import run_migrations
from app.db.postgres import close_pool, get_pool, init_pool
from app.db.redis import close_redis, init_redis
from app.ingestion.input import InputType, classify, normalize_url
from app.ingestion.orchestrator import resolve_recipe
from app.ingestion.parser import ExtractError, FetchError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core seeding logic — importable and testable without the CLI wrapper
# ---------------------------------------------------------------------------

async def run_seed(
    urls: list[str],
    concurrency: int = 10,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Seed the recipe DB from a list of URL strings.

    Skips blank lines and lines starting with '#'.  Each URL goes through
    the full orchestrator pipeline: Redis → Postgres → parse+insert.

    Returns a summary dict with keys:
        seeded   — newly parsed and inserted this run
        skipped  — already existed in DB (no parse needed)
        failed   — fetch / extract / other parse error
        errors   — {ErrorClassName: count} breakdown of failures
    """
    sem = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()
    start = time.monotonic()

    stats: dict = {
        "seeded": 0,
        "skipped": 0,
        "failed": 0,
        "errors": defaultdict(int),
    }

    async def process(raw: str) -> None:
        url = raw.strip()
        if not url or url.startswith("#"):
            return

        # Dry-run: classify and normalise only — no network or DB I/O
        if dry_run:
            try:
                if classify(url) == InputType.url:
                    canonical, url_hash = normalize_url(url)
                    print(f"[dry-run] url  hash={url_hash[:12]}  {canonical}")
                else:
                    print(f"[dry-run] skip (not a URL): {url}")
            except Exception as exc:
                print(f"[dry-run] error: {url}: {exc}", file=sys.stderr)
            return

        if stop.is_set():
            return

        async with sem:
            if stop.is_set():
                return
            try:
                # Fast pre-check: skip if already in Postgres
                _, url_hash = normalize_url(url)
                if await postgres.get_recipe_by_url_hash(url_hash):
                    stats["skipped"] += 1
                    return

                await resolve_recipe(url)
                stats["seeded"] += 1
                if limit and stats["seeded"] >= limit:
                    stop.set()

            except FetchError as exc:
                stats["failed"] += 1
                stats["errors"]["FetchError"] += 1
                logger.warning("FetchError %s: %s", url, exc)
            except ExtractError as exc:
                stats["failed"] += 1
                stats["errors"]["ExtractError"] += 1
                logger.warning("ExtractError %s: %s", url, exc)
            except Exception as exc:
                stats["failed"] += 1
                stats["errors"][type(exc).__name__] += 1
                logger.warning("%s for %s: %s", type(exc).__name__, url, exc)
            finally:
                total = stats["seeded"] + stats["skipped"] + stats["failed"]
                if total > 0 and total % 50 == 0:
                    elapsed = time.monotonic() - start
                    rate = total / elapsed if elapsed > 0 else 0.0
                    print(
                        f"[seeded {stats['seeded']}/{limit or '∞'}, "
                        f"skipped {stats['skipped']}, "
                        f"failed {stats['failed']}, "
                        f"rate {rate:.1f}/s]",
                        flush=True,
                    )

    await asyncio.gather(*[asyncio.create_task(process(u)) for u in urls])
    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    urls_path = Path(args.urls)
    if not urls_path.exists():
        print(f"error: file not found: {urls_path}", file=sys.stderr)
        sys.exit(1)

    raw_lines = urls_path.read_text().splitlines()
    active = [l for l in raw_lines if l.strip() and not l.strip().startswith("#")]
    print(f"Loaded {len(active)} URLs from {urls_path}", file=sys.stderr)

    if not args.dry_run:
        await init_pool()
        async with get_pool().acquire() as conn:
            await run_migrations(conn)
        await init_redis()

    try:
        stats = await run_seed(
            raw_lines,
            concurrency=args.concurrency,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    finally:
        if not args.dry_run:
            await close_redis()
            await close_pool()

    print("\n=== Seed complete ===", file=sys.stderr)
    print(f"  seeded  : {stats['seeded']}", file=sys.stderr)
    print(f"  skipped : {stats['skipped']}", file=sys.stderr)
    print(f"  failed  : {stats['failed']}", file=sys.stderr)
    if stats["errors"]:
        print("  breakdown:", file=sys.stderr)
        for name, count in sorted(stats["errors"].items()):
            print(f"    {name}: {count}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the CookBot recipe database from a newline-delimited URL file."
    )
    parser.add_argument("--urls", required=True, help="Path to URL file")
    parser.add_argument(
        "--concurrency", type=int, default=10, help="Max parallel parses (default: 10)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Stop after N successes"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and normalise only; no DB writes",
    )
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
