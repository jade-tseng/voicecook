"""Unit tests for tts.py — no server or API key required."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Provide a dummy API key so config.py doesn't raise at import time
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from tts import text_to_mp3_bytes


def test_tts_returns_bytes():
    audio = text_to_mp3_bytes("Boil the spaghetti for ten minutes.")
    assert isinstance(audio, bytes)


def test_tts_produces_nonempty_mp3():
    audio = text_to_mp3_bytes("Add salt to the pasta water.")
    assert len(audio) > 1000, "Expected at least 1KB of audio data"


def test_tts_mp3_header():
    audio = text_to_mp3_bytes("Remove the pan from heat.")
    # MP3 files start with an ID3 tag or a sync frame
    assert audio[:3] == b"ID3" or audio[:2] == b"\xff\xfb", (
        f"Unexpected MP3 header bytes: {audio[:4]!r}"
    )


def test_tts_different_texts_differ():
    a = text_to_mp3_bytes("Step one: boil water.")
    b = text_to_mp3_bytes("Step two: add pasta.")
    assert a != b
