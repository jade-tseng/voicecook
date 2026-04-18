"""Unit tests for llm.py — Gemini client is mocked, no API key needed."""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from llm import stream_recipe_answer


async def _fake_stream(chunks):
    for text in chunks:
        chunk = MagicMock()
        chunk.text = text
        yield chunk


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
            recipe_text="Recipe here",
            history=[],
            user_message="Can I use bacon?",
        ):
            result.append(chunk)

    assert result == fake_chunks


@pytest.mark.asyncio
async def test_stream_includes_history_in_messages():
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
            recipe_text="Recipe",
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
async def test_stream_system_prompt_contains_recipe():
    recipe = "Carbonara recipe details here"

    mock_generate = AsyncMock(return_value=_fake_stream(["Ok."]))

    mock_aio = MagicMock()
    mock_aio.models.generate_content_stream = mock_generate

    mock_client = MagicMock()
    mock_client.aio = mock_aio

    with patch("llm.genai.Client", return_value=mock_client):
        async for _ in stream_recipe_answer(
            recipe_text=recipe,
            history=[],
            user_message="Any question",
        ):
            pass

    system = mock_generate.call_args.kwargs["config"].system_instruction
    assert recipe in system
