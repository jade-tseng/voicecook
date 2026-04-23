"""Unit tests for llm.py — Gemini client is mocked, no API key needed."""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from llm import _format_recipe_for_prompt, stream_recipe_answer


class _Content:
    def __init__(self, role, parts): self.role = role; self.parts = parts

class _Part:
    def __init__(self, text): self.text = text

class _GCC:
    def __init__(self, system_instruction=None, max_output_tokens=None):
        self.system_instruction = system_instruction

@pytest.fixture()
def real_types():
    """Patch llm.types with concrete stubs so attribute access works in assertions."""
    fake = MagicMock()
    fake.Content = _Content
    fake.Part = _Part
    fake.GenerateContentConfig = _GCC
    with patch("llm.types", fake):
        yield fake


FAKE_RECIPE = {
    "title": "Carbonara",
    "servings": 4,
    "total_time_min": 25,
    "ingredients": [{"name": "spaghetti"}, {"name": "pancetta"}, {"name": "eggs"}],
    "instructions": [
        {"step": 1, "text": "Boil pasta."},
        {"step": 2, "text": "Fry pancetta."},
    ],
}


async def _fake_stream(chunks):
    for text in chunks:
        chunk = MagicMock()
        chunk.text = text
        yield chunk


# --- _format_recipe_for_prompt ---

def test_format_includes_title():
    assert "Recipe: Carbonara" in _format_recipe_for_prompt(FAKE_RECIPE)


def test_format_includes_servings_and_time():
    text = _format_recipe_for_prompt(FAKE_RECIPE)
    assert "Servings: 4" in text
    assert "Total time: 25 minutes" in text


def test_format_includes_ingredient_names():
    text = _format_recipe_for_prompt(FAKE_RECIPE)
    assert "- spaghetti" in text
    assert "- pancetta" in text
    assert "- eggs" in text


def test_format_includes_numbered_instructions():
    text = _format_recipe_for_prompt(FAKE_RECIPE)
    assert "1. Boil pasta." in text
    assert "2. Fry pancetta." in text


def test_format_handles_minimal_recipe():
    minimal = {"title": "Rice", "ingredients": [{"name": "rice"}],
               "instructions": [{"step": 1, "text": "Cook."}]}
    text = _format_recipe_for_prompt(minimal)
    assert "Recipe: Rice" in text
    assert "- rice" in text
    assert "1. Cook." in text


def test_format_omits_absent_servings_and_time():
    text = _format_recipe_for_prompt({"title": "X", "ingredients": [], "instructions": []})
    assert "Servings" not in text
    assert "Total time" not in text


# --- stream_recipe_answer ---

@pytest.mark.asyncio
async def test_stream_yields_text_chunks():
    fake_chunks = ["Sure", ", ", "add", " bacon", " instead."]

    mock_aio = MagicMock()
    mock_aio.models.generate_content_stream = AsyncMock(return_value=_fake_stream(fake_chunks))

    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("llm.genai.Client", return_value=mock_client):
        result = []
        async for chunk in stream_recipe_answer(
            recipe={"title": "Recipe", "ingredients": [], "instructions": []},
            history=[],
            user_message="Can I use bacon?",
        ):
            result.append(chunk)

    assert result == fake_chunks


@pytest.mark.asyncio
async def test_stream_includes_history_in_messages(real_types):
    history = [
        {"role": "user", "content": "How long does this take?"},
        {"role": "assistant", "content": "About 25 minutes."},
    ]

    mock_generate = AsyncMock(return_value=_fake_stream(["Yes."]))
    mock_aio = MagicMock()
    mock_aio.models.generate_content_stream = mock_generate
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("llm.genai.Client", return_value=mock_client):
        async for _ in stream_recipe_answer(
            recipe={"title": "Recipe", "ingredients": [], "instructions": []},
            history=history,
            user_message="Follow-up question",
        ):
            pass

    contents = mock_generate.call_args.kwargs["contents"]
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "How long does this take?"
    assert contents[1].role == "model"
    assert contents[1].parts[0].text == "About 25 minutes."
    assert contents[-1].role == "user"
    assert contents[-1].parts[0].text == "Follow-up question"


@pytest.mark.asyncio
async def test_stream_system_prompt_contains_recipe(real_types):
    recipe = {
        "title": "Carbonara",
        "ingredients": [{"name": "eggs"}],
        "instructions": [{"step": 1, "text": "Boil pasta."}],
    }

    mock_generate = AsyncMock(return_value=_fake_stream(["Ok."]))
    mock_aio = MagicMock()
    mock_aio.models.generate_content_stream = mock_generate
    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("llm.genai.Client", return_value=mock_client):
        async for _ in stream_recipe_answer(
            recipe=recipe,
            history=[],
            user_message="Any question",
        ):
            pass

    system = mock_generate.call_args.kwargs["config"].system_instruction
    assert "Carbonara" in system
    assert "eggs" in system
