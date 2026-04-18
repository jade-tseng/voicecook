import io

from gtts import gTTS

from config import settings


def text_to_mp3_bytes(text: str) -> bytes:
    """Convert text to MP3 audio bytes using gTTS."""
    buf = io.BytesIO()
    gTTS(text=text, lang=settings.tts_language, slow=False).write_to_fp(buf)
    buf.seek(0)
    return buf.read()
