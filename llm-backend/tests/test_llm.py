"""Unit tests for llm.py — Anthropic client is mocked, no API key needed."""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from llm import stream_recipe_answer


async def _fake_text_stream(chunks):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_stream_yields_text_chunks():
    fake_chunks = ["Sure", ", ", "add", " bacon", " instead."]

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.text_stream = _fake_text_stream(fake_chunks)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream

    with patch("llm.anthropic.AsyncAnthropic", return_value=mock_client):
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

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.text_stream = _fake_text_stream(["Yes."])

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream

    with patch("llm.anthropic.AsyncAnthropic", return_value=mock_client):
        async for _ in stream_recipe_answer(
            recipe_text="Recipe",
            history=history,
            user_message="Follow-up question",
        ):
            pass

    call_kwargs = mock_client.messages.stream.call_args.kwargs
    messages = call_kwargs["messages"]
    assert messages[:2] == history
    assert messages[-1] == {"role": "user", "content": "Follow-up question"}


@pytest.mark.asyncio
async def test_stream_system_prompt_contains_recipe():
    recipe = "Carbonara recipe details here"

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.text_stream = _fake_text_stream(["Ok."])

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream

    with patch("llm.anthropic.AsyncAnthropic", return_value=mock_client):
        async for _ in stream_recipe_answer(
            recipe_text=recipe,
            history=[],
            user_message="Any question",
        ):
            pass

    call_kwargs = mock_client.messages.stream.call_args.kwargs
    assert recipe in call_kwargs["system"]
