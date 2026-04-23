import httpx

from config import settings


class RecipeNotFoundError(Exception):
    pass


class RecipeUnparseableError(Exception):
    pass


class RecipeFetchError(Exception):
    pass


class RecipeServiceError(Exception):
    pass


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.ingestion_service_url,
            timeout=settings.ingestion_timeout_seconds,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def resolve_recipe(input_str: str) -> dict:
    client = get_client()
    try:
        resp = await client.post("/recipes/resolve", json={"input": input_str})
    except httpx.RequestError as exc:
        raise RecipeServiceError(str(exc)) from exc

    if resp.status_code == 404:
        raise RecipeNotFoundError("no recipe found")
    if resp.status_code == 422:
        raise RecipeUnparseableError(resp.json().get("detail", "unprocessable"))
    if resp.status_code == 502:
        raise RecipeFetchError(resp.json().get("detail", "fetch failed"))
    if not resp.is_success:
        raise RecipeServiceError(f"unexpected status {resp.status_code}")

    return resp.json()


