"""
Application configuration.

Centralized, type-safe configuration powered by Pydantic v2 Settings.
Values are read from environment variables / a local `.env` file, validated
once at process start, and exposed as a cached singleton via `get_settings()`.
"""
from functools import lru_cache
from typing import List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- General -------------------------------------------------------
    APP_NAME: str = "Cüzdanım"
    APP_VERSION: str = "1.2.0"  # keep in sync with APP_VERSION in app/static/app.js
    ENVIRONMENT: str = Field(default="development", pattern="^(development|staging|production)$")
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # --- Database --------------------------------------------------------
    # Async driver required: `sqlite+aiosqlite://` for local demo,
    # `postgresql+asyncpg://` for production. On Vercel, the Neon storage
    # integration injects `DATABASE_URL` (and legacy `POSTGRES_URL`) itself —
    # either name is picked up automatically, no manual copy-paste needed.
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./finance_tracker.db",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL"),
    )
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Neon/Vercel hand out a plain `postgres://...?sslmode=require&channel_binding=require`
        connection string. SQLAlchemy's async engine needs the `+asyncpg` driver, and
        asyncpg's own connect() rejects any query param it doesn't recognise — it wants
        `ssl=require` (not the psycopg-style `sslmode=`) and knows nothing about
        `channel_binding` (a libpq/SCRAM option asyncpg doesn't implement), so that one
        must be dropped rather than renamed."""
        if value.startswith("sqlite"):
            return value
        if value.startswith("postgres://"):
            value = "postgresql+asyncpg://" + value[len("postgres://"):]
        elif value.startswith("postgresql://") and "+asyncpg" not in value.split("://", 1)[0]:
            value = "postgresql+asyncpg://" + value[len("postgresql://"):]

        scheme, netloc, path, query, fragment = urlsplit(value)
        params = dict(parse_qsl(query, keep_blank_values=True))
        params.pop("channel_binding", None)
        if params.pop("sslmode", None) in ("require", "verify-full", "verify-ca", "prefer"):
            params["ssl"] = "require"
        return urlunsplit((scheme, netloc, path, urlencode(params), fragment))

    # --- Security / Auth -------------------------------------------------
    SECRET_KEY: str = Field(
        default="CHANGE_ME_super_secret_key_please_replace_in_production_env",
        min_length=32,
        description="HMAC signing key for JWTs. MUST be overridden in production.",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Business rules ----------------------------------------------------
    BUDGET_ALERT_THRESHOLD: float = Field(default=0.8, ge=0.0, le=1.0)
    CURRENCY_SYMBOL: str = "₺"
    DEFAULT_LOCALE: str = "tr"

    # --- Scheduler ---------------------------------------------------------
    SCHEDULER_TIMEZONE: str = "Europe/Istanbul"
    ENABLE_SCHEDULER: bool = True
    DAILY_MESSAGE_HOUR: int = Field(default=8, ge=0, le=23)   # daily motivation push time
    DAILY_MESSAGE_MINUTE: int = Field(default=0, ge=0, le=59)
    BUDGET_CHECK_HOUR: int = Field(default=20, ge=0, le=23)   # evening budget check

    # --- Web Push (VAPID) --------------------------------------------------
    # Leave empty to auto-generate keys into VAPID_KEYS_FILE on first start.
    # On ephemeral hosts (Render/Fly) set these env vars so subscriptions
    # survive redeploys — print them with: python -m app.tools.vapid
    VAPID_PRIVATE_KEY: str | None = None   # PEM (multi-line, "\n" escaped is fine)
    VAPID_PUBLIC_KEY: str | None = None    # base64url raw public key
    VAPID_CLAIMS_EMAIL: str = "mailto:admin@example.com"
    VAPID_KEYS_FILE: str = "vapid_keys.json"

    # --- CORS ----------------------------------------------------------------
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, value):
        """Allow `CORS_ORIGINS=http://a.com,http://b.com` as well as JSON list syntax."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance (parsed once)."""
    return Settings()


settings = get_settings()
