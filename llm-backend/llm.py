from typing import AsyncIterator

from google import genai
from google.genai import types

from config import settings

SYSTEM_PROMPT = (
    "You are VoiceCook, a friendly voice-based recipe assistant. "
    "Answer questions about the recipe concisely and conversationally, "
    "as your response will be read aloud. "
    "Do not use bullet points, numbered lists, or markdown formatting. "
    "Keep answers under three sentences unless the user asks for detail."
)


def _build_contents(
    history: list[dict], user_message: str
) -> list[types.Content]:
    """Convert our history format to Gemini's Content objects."""
    contents: list[types.Content] = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else msg["role"]
        contents.append(
            types.Content(role=role, parts=[types.Part(text=msg["content"])])
        )
    contents.append(
        types.Content(role="user", parts=[types.Part(text=user_message)])
    )
    return contents


async def stream_recipe_answer(
    recipe_text: str,
    history: list[dict],
    user_message: str,
) -> AsyncIterator[str]:
    client = genai.Client(api_key=settings.gemini_api_key)
    system = f"{SYSTEM_PROMPT}\n\nRecipe context:\n{recipe_text}"
    contents = _build_contents(history, user_message)

    try:
        stream = await client.aio.models.generate_content_stream(
            model=settings.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=512,
            ),
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text
    except genai.errors.APIError as exc:
        raise RuntimeError(f"Gemini API error: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Stream failed: {exc}") from exc
