from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://upstage:upstage@localhost:5432/compliance"
    upstage_api_key: str = ""
    secret_key: str = "change-me"
    environment: str = "development"


settings = Settings()
