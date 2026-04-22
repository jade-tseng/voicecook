from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    tts_language: str = "en"

    class Config:
        env_file = ".env"


settings = Settings()
