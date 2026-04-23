from google.cloud import speech

from config import settings

_client: speech.SpeechClient | None = None


def _get_client() -> speech.SpeechClient:
    global _client
    if _client is None:
        _client = speech.SpeechClient()
    return _client


def transcribe_audio(audio_bytes: bytes, encoding: str = "WEBM_OPUS") -> str:
    """
    Transcribe browser-recorded audio to text via Google Cloud STT.

    The browser's MediaRecorder produces WebM/Opus by default on Chrome/Firefox,
    which maps to WEBM_OPUS here. Pass encoding="LINEAR16" for raw PCM.
    """
    client = _get_client()

    enc = getattr(speech.RecognitionConfig.AudioEncoding, encoding)

    config = speech.RecognitionConfig(
        encoding=enc,
        language_code=settings.stt_language_code,
        enable_automatic_punctuation=True,
        model="latest_long",          # best accuracy for general speech
    )

    response = client.recognize(
        config=config,
        audio=speech.RecognitionAudio(content=audio_bytes),
    )

    if not response.results:
        return ""

    return " ".join(
        result.alternatives[0].transcript
        for result in response.results
        if result.alternatives
    )
