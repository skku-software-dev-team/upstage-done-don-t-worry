import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://upstage:upstage@localhost:5432/compliance"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = _DEFAULT_DATABASE_URL
    upstage_api_key: str = ""
    secret_key: str = "change-me"
    environment: str = "development"

    @model_validator(mode="after")
    def _normalize_database_url(self) -> "Settings":
        url = self.database_url
        if url == _DEFAULT_DATABASE_URL:
            # Vercel's Neon integration injects POSTGRES_URL (not DATABASE_URL),
            # and its value can't be copied out through the dashboard once
            # marked sensitive, so read it directly instead.
            url = os.environ.get("POSTGRES_URL", url)
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        url = url.replace("sslmode=", "ssl=")
        self.database_url = url
        return self


settings = Settings()
