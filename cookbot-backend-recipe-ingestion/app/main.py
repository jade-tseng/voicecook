import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.recipes import router as recipes_router
from app.db.migrate import run_migrations
from app.db.postgres import close_pool, get_pool, init_pool
from app.db.redis import close_redis, init_redis
from app.ingestion.orchestrator import RecipeNotFound
from app.ingestion.parser import ExtractError, FetchError, ParseError
from app.logging import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_pool()
    async with get_pool().acquire() as conn:
        await run_migrations(conn)
    await init_redis()
    yield
    await close_redis()
    await close_pool()


app = FastAPI(title="CookBot API", lifespan=lifespan)
app.include_router(recipes_router)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(FetchError)
async def _fetch_error(_: Request, exc: FetchError) -> JSONResponse:
    logger.warning("FetchError: %s", exc)
    return JSONResponse(status_code=502, content={"detail": "could not fetch recipe url"})


@app.exception_handler(ExtractError)
async def _extract_error(_: Request, exc: ExtractError) -> JSONResponse:
    logger.warning("ExtractError: %s", exc)
    return JSONResponse(status_code=422, content={"detail": "could not extract recipe from page"})


@app.exception_handler(ParseError)
async def _parse_error(_: Request, exc: ParseError) -> JSONResponse:
    logger.warning("ParseError: %s", exc)
    return JSONResponse(status_code=502, content={"detail": "recipe parse failed"})


@app.exception_handler(RecipeNotFound)
async def _not_found(_: Request, exc: RecipeNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "no recipe found for input"})


@app.exception_handler(ValueError)
async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
