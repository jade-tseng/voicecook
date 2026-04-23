import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, model_validator

import recipe_client
from llm import stream_recipe_answer
from mock_data import MOCK_RECIPE
from recipe_client import (
    RecipeFetchError,
    RecipeNotFoundError,
    RecipeServiceError,
    RecipeUnparseableError,
)
from session_store import (
    append_history,
    create_session,
    delete_session,
    get_session,
)
from tts import text_to_mp3_bytes


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await recipe_client.close_client()


app = FastAPI(title="VoiceCook LLM Backend", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Exception handlers ---

@app.exception_handler(RecipeNotFoundError)
async def _recipe_not_found(request: Request, exc: RecipeNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RecipeUnparseableError)
async def _recipe_unparseable(request: Request, exc: RecipeUnparseableError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(RecipeFetchError)
async def _recipe_fetch_error(request: Request, exc: RecipeFetchError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(RecipeServiceError)
async def _recipe_service_error(request: Request, exc: RecipeServiceError):
    return JSONResponse(status_code=503, content={"detail": "recipe service unavailable"})


# --- Request / Response models ---

class SessionCreateRequest(BaseModel):
    """Create a session from recipe_text, use_mock, or recipe_input (URL or dish name)."""
    recipe_text: str | None = None
    use_mock: bool = False
    recipe_input: str | None = None  # URL or dish name passed to ingestion service
    recipe_url: str | None = None    # backward-compat alias for recipe_input

    @model_validator(mode="after")
    def _merge_recipe_url(self):
        if self.recipe_input is None and self.recipe_url is not None:
            self.recipe_input = self.recipe_url
        return self


class SessionCreateResponse(BaseModel):
    session_id: str
    recipe: dict


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
async def create_new_session(req: SessionCreateRequest):
    if req.recipe_input is not None and not req.use_mock:
        recipe = await recipe_client.resolve_recipe(req.recipe_input)
    else:
        # TODO: clean up mock path post-demo
        recipe_text = req.recipe_text if req.recipe_text is not None else MOCK_RECIPE
        recipe = {
            "title": "Recipe",
            "ingredients": [],
            "instructions": [{"step": 1, "text": recipe_text}],
            "servings": None,
            "total_time_min": None,
        }

    sid = create_session(recipe)
    return SessionCreateResponse(session_id=sid, recipe=recipe)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    session = get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    accumulated: list[str] = []

    async def event_generator():
        try:
            async for chunk in stream_recipe_answer(
                recipe=session["recipe"],
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
