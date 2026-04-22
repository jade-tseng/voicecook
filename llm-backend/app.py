import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from llm import stream_recipe_answer
from mock_data import MOCK_RECIPE
from session_store import (
    append_history,
    create_session,
    delete_session,
    get_session,
)
from tts import text_to_mp3_bytes

app = FastAPI(title="VoiceCook LLM Backend")


# --- Request / Response models ---

class SessionCreateRequest(BaseModel):
    recipe_text: str | None = None
    use_mock: bool = False
    recipe_url: str | None = None  # placeholder for future scraper


class SessionCreateResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    session_id: str
    message: str


class TTSRequest(BaseModel):
    text: str


# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "service": "voicecook-llm-backend"}


@app.post("/session", response_model=SessionCreateResponse)
def create_new_session(req: SessionCreateRequest):
    if req.use_mock or (req.recipe_text is None and req.recipe_url is None):
        recipe_text = MOCK_RECIPE
    elif req.recipe_url is not None:
        # Future: recipe_text = scraper.extract(req.recipe_url)
        raise HTTPException(status_code=501, detail="URL scraping not yet implemented")
    else:
        recipe_text = req.recipe_text

    sid = create_session(recipe_text)
    return SessionCreateResponse(session_id=sid)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    session = get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    accumulated: list[str] = []

    async def event_generator():
        try:
            async for chunk in stream_recipe_answer(
                recipe_text=session["recipe_text"],
                history=session["history"],
                user_message=req.message,
            ):
                accumulated.append(chunk)
                yield f"data: {chunk}\n\n"

            full_response = "".join(accumulated)
            append_history(req.session_id, "user", req.message)
            append_history(req.session_id, "assistant", full_response)
            yield "data: [DONE]\n\n"
        except Exception as exc:
            yield f"data: [ERROR] {exc}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/tts")
async def tts_endpoint(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    audio_bytes = await asyncio.to_thread(text_to_mp3_bytes, req.text)
    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "attachment; filename=response.mp3"},
    )


@app.delete("/session/{session_id}", status_code=204)
def delete_session_endpoint(session_id: str):
    delete_session(session_id)
