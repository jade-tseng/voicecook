"""
Integration tests — require a live server and GEMINI_API_KEY.

Start the server before running:
    cd llm-backend && uvicorn app:app --port 8001

Run with:
    GEMINI_API_KEY=... pytest tests/test_pipeline.py -v
"""
import pytest
import httpx

BASE_URL = "http://localhost:8001"


@pytest.fixture(scope="module")
def session_id():
    resp = httpx.post(f"{BASE_URL}/session", json={"use_mock": True})
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


def test_health():
    resp = httpx.get(f"{BASE_URL}/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_session_with_mock():
    resp = httpx.post(f"{BASE_URL}/session", json={"use_mock": True})
    assert resp.status_code == 200
    assert "session_id" in resp.json()


def test_create_session_with_custom_text():
    resp = httpx.post(
        f"{BASE_URL}/session",
        json={"recipe_text": "Simple omelette: 2 eggs, butter, salt."},
    )
    assert resp.status_code == 200
    assert "session_id" in resp.json()


def test_chat_stream_returns_text(session_id):
    chunks = []
    with httpx.stream(
        "POST",
        f"{BASE_URL}/chat/stream",
        json={"session_id": session_id, "message": "How long does this take to make?"},
        timeout=30,
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                chunks.append(line[6:])

    full_text = "".join(chunks)
    assert len(full_text) > 10, f"Expected a real answer, got: {full_text!r}"


def test_tts_returns_mp3():
    resp = httpx.post(
        f"{BASE_URL}/tts",
        json={"text": "Boil the pasta until al dente, about ten minutes."},
        timeout=15,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert len(resp.content) > 1000
    assert resp.content[:3] == b"ID3" or resp.content[0:1] == b"\xff"


def test_tts_rejects_empty_text():
    resp = httpx.post(f"{BASE_URL}/tts", json={"text": "   "})
    assert resp.status_code == 400


def test_full_pipeline(session_id):
    """End-to-end: user question → streamed LLM answer → TTS audio bytes."""
    # Step 1: stream LLM answer
    text_chunks = []
    with httpx.stream(
        "POST",
        f"{BASE_URL}/chat/stream",
        json={
            "session_id": session_id,
            "message": "Why should I never add cream to carbonara?",
        },
        timeout=30,
    ) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                text_chunks.append(line[6:])

    full_answer = "".join(text_chunks)
    assert len(full_answer) > 0, "LLM returned no text"

    # Step 2: convert answer to audio
    audio_resp = httpx.post(
        f"{BASE_URL}/tts",
        json={"text": full_answer},
        timeout=20,
    )
    assert audio_resp.status_code == 200
    assert len(audio_resp.content) > 1000, "Audio output too small"


def test_conversation_history_is_maintained(session_id):
    """Second question in the same session should produce a coherent answer."""
    for question in [
        "What cheese is used in this recipe?",
        "Is there a substitute for Pecorino Romano?",
    ]:
        chunks = []
        with httpx.stream(
            "POST",
            f"{BASE_URL}/chat/stream",
            json={"session_id": session_id, "message": question},
            timeout=30,
        ) as r:
            assert r.status_code == 200
            for line in r.iter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunks.append(line[6:])
        assert len("".join(chunks)) > 0


def test_delete_session():
    resp = httpx.post(f"{BASE_URL}/session", json={"use_mock": True})
    sid = resp.json()["session_id"]

    del_resp = httpx.delete(f"{BASE_URL}/session/{sid}")
    assert del_resp.status_code == 204

    # Streaming on a deleted session should 404
    stream_resp = httpx.post(
        f"{BASE_URL}/chat/stream",
        json={"session_id": sid, "message": "hello"},
    )
    assert stream_resp.status_code == 404
