from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    tts_language: str = "en"
    ingestion_service_url: str = "http://localhost:8000"
    ingestion_timeout_seconds: float = 15.0

    class Config:
        env_file = ".env"


settings = Settings()
