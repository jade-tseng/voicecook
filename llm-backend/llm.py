from typing import AsyncIterator

import anthropic

from config import settings

SYSTEM_PROMPT = (
    "You are VoiceCook, a friendly voice-based recipe assistant. "
    "Answer questions about the recipe concisely and conversationally, "
    "as your response will be read aloud. "
    "Do not use bullet points, numbered lists, or markdown formatting. "
    "Keep answers under three sentences unless the user asks for detail."
)


async def stream_recipe_answer(
    recipe_text: str,
    history: list[dict],
    user_message: str,
) -> AsyncIterator[str]:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system = f"{SYSTEM_PROMPT}\n\nRecipe context:\n{recipe_text}"
    messages = history + [{"role": "user", "content": user_message}]

    async with client.messages.stream(
        model=settings.claude_model,
        max_tokens=512,
        system=system,
        messages=messages,
    ) as stream:
        async for text_chunk in stream.text_stream:
            yield text_chunk
