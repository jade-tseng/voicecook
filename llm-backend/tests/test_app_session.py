import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")

# Stub packages not installed in the test environment so app.py can be imported
for _mod in ("google", "google.genai", "google.genai.types", "google.genai.errors", "gtts"):
    sys.modules.setdefault(_mod, MagicMock())

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import recipe_client
from recipe_client import RecipeNotFoundError, RecipeServiceError, RecipeUnparseableError

FAKE_RECIPE_DICT = {
    "id": "abc",
    "title": "Test Pasta",
    "ingredients": [{"name": "pasta", "quantity": "200", "unit": "g"}],
    "instructions": [{"step": 1, "text": "Cook pasta."}],
    "servings": 2,
    "total_time_min": 10,
}


@pytest.fixture()
def client():
    from app import app
    with TestClient(app) as c:
        yield c


# --- /session ---

def test_session_with_ingestion_success(client, monkeypatch):
    monkeypatch.setattr(recipe_client, "resolve_recipe", AsyncMock(return_value=FAKE_RECIPE_DICT))

    resp = client.post("/session", json={"recipe_input": "https://example.com/pasta"})
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert body["recipe"]["title"] == "Test Pasta"
    assert body["recipe"]["ingredients"][0]["name"] == "pasta"


def test_session_recipe_url_alias(client, monkeypatch):
    """recipe_url is a backward-compat alias for recipe_input."""
    monkeypatch.setattr(recipe_client, "resolve_recipe", AsyncMock(return_value=FAKE_RECIPE_DICT))

    resp = client.post("/session", json={"recipe_url": "https://example.com/pasta"})
    assert resp.status_code == 200
    assert resp.json()["recipe"]["title"] == "Test Pasta"


def test_session_recipe_not_found_returns_404(client, monkeypatch):
    monkeypatch.setattr(
        recipe_client,
        "resolve_recipe",
        AsyncMock(side_effect=RecipeNotFoundError("no recipe found")),
    )
    resp = client.post("/session", json={"recipe_input": "made up dish xyz"})
    assert resp.status_code == 404
    assert "no recipe found" in resp.json()["detail"]


def test_session_unparseable_returns_422(client, monkeypatch):
    monkeypatch.setattr(
        recipe_client,
        "resolve_recipe",
        AsyncMock(side_effect=RecipeUnparseableError("bad input")),
    )
    resp = client.post("/session", json={"recipe_input": "???"})
    assert resp.status_code == 422


def test_session_service_error_returns_503(client, monkeypatch):
    monkeypatch.setattr(
        recipe_client,
        "resolve_recipe",
        AsyncMock(side_effect=RecipeServiceError("down")),
    )
    resp = client.post("/session", json={"recipe_input": "https://example.com/pasta"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "recipe service unavailable"


def test_session_falls_back_to_mock_when_no_input(client):
    resp = client.post("/session", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert "recipe" in body


def test_session_use_mock_flag(client):
    resp = client.post("/session", json={"use_mock": True})
    assert resp.status_code == 200
    assert "recipe" in resp.json()


def test_session_with_recipe_text(client):
    resp = client.post("/session", json={"recipe_text": "Simple recipe: boil water."})
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert "recipe" in body


# --- structured recipe flows through to chat/stream prompt ---

def test_chat_stream_receives_structured_recipe(client, monkeypatch):
    """The recipe dict stored in the session is passed to _format_recipe_for_prompt."""
    monkeypatch.setattr(recipe_client, "resolve_recipe", AsyncMock(return_value=FAKE_RECIPE_DICT))
    create_resp = client.post("/session", json={"recipe_input": "https://example.com/pasta"})
    assert create_resp.status_code == 200
    sid = create_resp.json()["session_id"]

    async def fake_gen():
        chunk = MagicMock()
        chunk.text = "Looks good!"
        yield chunk

    async def fake_generate(*args, **kwargs):
        return fake_gen()

    mock_aio = MagicMock()
    mock_aio.models.generate_content_stream = fake_generate
    mock_gemini = MagicMock()
    mock_gemini.aio = mock_aio

    with patch("llm.genai.Client", return_value=mock_gemini), \
         patch("llm._format_recipe_for_prompt") as mock_fmt:
        mock_fmt.return_value = "Test Pasta\nIngredients:\n- pasta"
        resp = client.post("/chat/stream", json={"session_id": sid, "message": "What are the ingredients?"})

    assert resp.status_code == 200
    mock_fmt.assert_called_once_with(FAKE_RECIPE_DICT)
