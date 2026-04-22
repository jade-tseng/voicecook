from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://cookbot:cookbot@localhost:5432/cookbot"
    redis_url: str = "redis://localhost:6379/0"

    # cache TTLs (seconds)
    redis_ttl_recipe: int = 60 * 60 * 24 * 7  # 7 days


settings = Settings()
