"""
Application configuration.

Centralized, type-safe configuration powered by Pydantic v2 Settings.
Values are read from environment variables / a local `.env` file, validated
once at process start, and exposed as a cached singleton via `get_settings()`.
"""
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- General -------------------------------------------------------
    APP_NAME: str = "Cüzdanım"
    APP_VERSION: str = "1.1.0"  # keep in sync with APP_VERSION in app/static/app.js
    ENVIRONMENT: str = Field(default="development", pattern="^(development|staging|production)$")
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # --- Database --------------------------------------------------------
    # Async driver required: `sqlite+aiosqlite://` for local demo,
    # `postgresql+asyncpg://` for production.
    DATABASE_URL: str = "sqlite+aiosqlite:///./finance_tracker.db"
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

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
