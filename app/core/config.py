"""Application settings, read from the environment and `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-only-change-me-dev-only-change-me"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "Mandy API"
    log_level: str = "INFO"
    log_json: bool | None = None  # default: JSON outside dev

    database_url: str = "postgresql+asyncpg://mandy:mandy@localhost:5433/mandy"
    test_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr(DEFAULT_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    recovery_token_minutes: int = 10

    cors_origins: list[str] = ["http://localhost:3001"]

    rp_id: str = "localhost"
    rp_name: str = "Mandy"
    origin: str = "http://localhost:3001"

    dev_login_enabled: bool = False

    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"

    rate_limit_per_minute: int = 5
    max_body_bytes: int = 1_048_576
    news_cache_seconds: int = 300
    dashboard_cache_seconds: int = 60
    news_feeds_enabled: bool = True

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.env == "prod":
            secret = self.jwt_secret.get_secret_value()
            if secret == DEFAULT_JWT_SECRET or len(secret) < 32:
                raise ValueError("JWT_SECRET must be set to a random value of 32+ chars in prod")
            if self.dev_login_enabled:
                raise ValueError("DEV_LOGIN_ENABLED must be false in prod")
        return self

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def cookie_secure(self) -> bool:
        """Secure cookies everywhere except local dev/test over plain http."""
        return self.env == "prod"

    @property
    def dev_login_active(self) -> bool:
        return self.env == "dev" and self.dev_login_enabled

    @property
    def ai_enabled(self) -> bool:
        return bool(self.gemini_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
