import uuid
from typing import TypedDict


class SessionData(TypedDict):
    recipe_text: str
    history: list[dict]


_store: dict[str, SessionData] = {}


def create_session(recipe_text: str) -> str:
    sid = str(uuid.uuid4())
    _store[sid] = {"recipe_text": recipe_text, "history": []}
    return sid


def get_session(sid: str) -> SessionData | None:
    return _store.get(sid)


def append_history(sid: str, role: str, content: str) -> None:
    _store[sid]["history"].append({"role": role, "content": content})


def delete_session(sid: str) -> None:
    _store.pop(sid, None)
