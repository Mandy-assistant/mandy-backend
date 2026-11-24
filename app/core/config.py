"""Application settings, read from the environment and `.env`."""

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Versions this build can serve; `API_VERSION` picks one (see app/api/__init__.py).
ApiVersion = Literal["v1", "v2"]

DEFAULT_JWT_SECRET = "dev-only-change-me-dev-only-change-me"  # noqa: S105

# libpq options that asyncpg doesn't accept as-is.
_SSL_ALIASES = {"sslmode": "ssl"}
_DROPPED_PARAMS = {"channel_binding"}


def to_asyncpg_url(url: str) -> str:
    """Make a plain `postgres://` URL (as Neon or Render hand out) usable by SQLAlchemy + asyncpg.

    Sets the `postgresql+asyncpg` driver, renames `sslmode` to asyncpg's `ssl`, and drops
    `channel_binding` (asyncpg rejects it; the connection still uses SCRAM over TLS).
    """
    # Dashboards keep quotes pasted from a .env line (DATABASE_URL="postgresql://...").
    url = url.strip().strip("'\"").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql", "postgresql+asyncpg"):
        raise ValueError(
            "must be a Postgres URL starting with postgresql:// "
            f"(got one starting with {url[:12]!r})"
        )
    query = [
        (_SSL_ALIASES.get(key, key), value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _DROPPED_PARAMS
    ]
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", query=urlencode(query)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "Mandy API"
    log_level: str = "INFO"
    log_json: bool | None = None  # default: JSON outside dev

    # Which API version this process serves, mounted at /api/<version>. Others are not exposed.
    api_version: ApiVersion = "v1"

    database_url: str = "postgresql+asyncpg://mandy:mandy@localhost:5433/mandy"
    # Direct (non-pooled) connection, used for migrations when set. `neon env pull` provides it.
    database_url_unpooled: str | None = None
    test_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    # Tests flush this database before every test; keep it local when REDIS_URL is a hosted store.
    test_redis_url: str | None = None

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
    # Pull news / job boards again when the last pull is older than this (on the next visit).
    news_refresh_minutes: int = 30
    jobs_refresh_minutes: int = 180
    # Reddit only answers servers with OAuth: create a free "script" app at reddit.com/prefs/apps
    reddit_client_id: str = ""
    reddit_client_secret: SecretStr = SecretStr("")
    reddit_subreddits: list[str] = []

    @field_validator("database_url", "database_url_unpooled", "test_database_url")
    @classmethod
    def _asyncpg_url(cls, value: str | None) -> str | None:
        return to_asyncpg_url(value) if value else value

    @field_validator("api_version", mode="before")
    @classmethod
    def _api_version(cls, value: object) -> object:
        # Accept "V1", "/v1" or " v1 " as v1.
        if isinstance(value, str):
            return value.strip().strip("'\"").strip("/").lower()
        return value

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        # Browsers report the origin without a trailing slash; WebAuthn compares it exactly.
        return value.strip().strip("'\"").rstrip("/")

    @field_validator("rp_id")
    @classmethod
    def _rp_id(cls, value: str) -> str:
        # The RP ID is a bare host: accept a pasted URL and keep only the host.
        host = value.strip().strip("'\"")
        host = host.split("://", 1)[-1]
        return host.split("/", 1)[0].split(":", 1)[0]

    @field_validator("cors_origins")
    @classmethod
    def _cors(cls, value: list[str]) -> list[str]:
        return [o.strip().rstrip("/") for o in value]

    @field_validator("redis_url", "test_redis_url")
    @classmethod
    def _strip_quotes(cls, value: str | None) -> str | None:
        return value.strip().strip("'\"").strip() if value else value

    @property
    def uses_connection_pooler(self) -> bool:
        """Neon's pooled host (`-pooler.`) runs PgBouncer in transaction mode."""
        return "-pooler." in (urlsplit(self.database_url).hostname or "")

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
    def api_prefix(self) -> str:
        return f"/api/{self.api_version}"

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
