# Cook Bot — Ingestion Backend

Recipe ingestion service for Cook Bot. Takes a URL or dish name, returns a structured recipe. Backed by Postgres (durable) + Redis (hot cache).

## Quick start

Requires Docker Desktop (Mac/Windows) or Docker Engine + Compose (Linux). Nothing else.

    git clone <repo-url>
    cd cookbot-backend
    docker compose up --build

Wait ~30s for Postgres, Redis, and the API to come up. Then:

    curl localhost:8000/health
    # {"status":"ok"}

Interactive API docs: <http://localhost:8000/docs>

## What it does

One endpoint: `POST /recipes/resolve`

    curl -X POST localhost:8000/recipes/resolve \
      -H "Content-Type: application/json" \
      -d '{"input": "https://www.allrecipes.com/recipe/213742/cheesy-ham-and-hash-brown-casserole/"}'

Accepts a URL or a dish name. Returns a structured `RecipeRecord` JSON.

Pipeline:

1. Classify input (URL vs name) and normalize
2. Check Redis (hot cache, ~1ms)
3. Check Postgres (durable store, ~10ms)
4. On miss: parse the URL via `recipe-scrapers` (fallback: JSON-LD via `extruct`). For names: alias lookup → Postgres full-text search → web search stub
5. Write to Postgres, warm Redis, return

## Seed the database

An empty database means name search always misses. Seed with the example URL list:

    make seed URLS=seed_urls.example.txt

Or supply your own newline-delimited file of recipe URLs:

    make seed URLS=my_urls.txt

Options passed directly to the seeder:

    docker compose exec api python -m scripts.seed \
      --urls /app/seed_urls.example.txt \
      --concurrency 10 \
      --limit 1000

## Run tests

    docker compose exec api pytest

124 tests. Integration tests run against the real Postgres and Redis containers.

## Inspect

**Database:**

    docker compose exec postgres psql -U cookbot -d cookbot
    # \dt          -- list tables
    # SELECT id, title FROM recipes;
    # \q

**Redis:**

    docker compose exec redis redis-cli
    # KEYS recipe:*
    # GET recipe:url:<hash>
    # TTL recipe:url:<hash>
    # exit

**Logs:**

    docker compose logs -f api

Structured JSON lines per request: `input_type`, `cache_layer`, `match_type`, `latency_ms`, `outcome`, `error_type`.

## Stop

    docker compose down       # keeps data in the pgdata volume
    docker compose down -v    # wipes the database

## Port conflicts

If you already run Postgres on 5432 or Redis on 6379 locally, edit `docker-compose.yml` to remap the host-side port:

    postgres:
      ports: ["55432:5432"]

Service-to-service traffic inside the Docker network still uses 5432 — only the host-exposed port changes.

## Project layout

    app/
      main.py                 FastAPI entry, lifespan, exception handlers
      config.py               env var loader
      api/recipes.py          POST /recipes/resolve router
      db/
        postgres.py           asyncpg pool + query helpers
        redis.py              async Redis client + cache helpers
        migrate.py            SQL migration runner
      ingestion/
        input.py              URL/name classification + normalization
        parser.py             URL -> RecipeBase (recipe-scrapers + extruct)
        resolver.py           name -> recipe_id or URL (alias -> FTS -> web)
        orchestrator.py       ties it all together, the pipeline
      models/recipe.py        Pydantic schemas
    migrations/
      001_init.sql            recipes + recipe_name_aliases tables
    scripts/seed.py           batch-load URLs into the DB
    tests/                    124 tests, run via pytest

## Stack

Python 3.12 · FastAPI · Uvicorn · asyncpg · redis-py · httpx · recipe-scrapers · extruct · Postgres 16 · Redis 7 · Docker Compose

## Integration (for downstream services)

The LLM backend calls this service over HTTP. Never the frontend directly.

Contract:

    POST /recipes/resolve
    Body:    {"input": "<url or dish name>"}
    200:     RecipeRecord JSON
    404:     no recipe found for input
    422:     bad input / could not extract recipe from page
    502:     could not fetch recipe url

See `app/models/recipe.py` for the full `RecipeRecord` schema.

## Deployment

Targets GCP Cloud Run (stateless), Cloud SQL (Postgres), Memorystore (Redis). Not deployed yet — local Docker Compose only.
