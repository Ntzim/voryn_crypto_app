"""Application settings, loaded from environment variables (12-factor)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Environment = "development"
    app_name: str = "Voryn API"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+asyncpg://voryn:voryn@localhost:5432/voryn"
    database_pool_size: int = 10
    redis_url: str = "redis://localhost:6379/0"

    # Used to HMAC opaque tokens (sessions, e-mail links) before storage.
    secret_key: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    # Comma-separated Fernet keys. The first encrypts; all are tried to decrypt (rotation).
    encryption_keys: Annotated[list[SecretStr], NoDecode] = Field(default_factory=list)

    frontend_url: str = "http://localhost:3000"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Only enable behind a proxy you control (the Next.js BFF / Railway edge).
    trust_proxy_headers: bool = False

    # Multiplies every rate limit. Keep 1 in production; raise locally for e2e test runs.
    rate_limit_scale: int = Field(default=1, ge=1, le=1000)

    session_cookie_name: str = "voryn_session"
    csrf_cookie_name: str = "voryn_csrf"
    cookie_secure: bool = True
    session_ttl_days: int = 30
    session_idle_days: int = 7

    email_backend: Literal["smtp", "console", "memory"] = "console"
    # "queue" hands delivery to the Celery worker so request latency never depends on SMTP.
    email_delivery: Literal["queue", "inline"] = "queue"
    email_from: str = "Voryn <no-reply@voryn.app>"
    # "off" disables enqueuing background jobs (tests).
    background_tasks: Literal["queue", "off"] = "queue"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False

    email_verification_ttl_hours: int = 48
    password_reset_ttl_minutes: int = 30

    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    coingecko_api_key: SecretStr | None = None
    coingecko_api_plan: Literal["public", "demo", "pro"] = "public"
    binance_base_url: str = "https://data-api.binance.vision"
    #: signed (account) endpoints; used only with the user's read-only keys
    binance_private_base_url: str = "https://api.binance.com"
    market_top_n: int = Field(default=100, ge=1, le=250)
    market_sync_interval_seconds: int = Field(default=300, ge=60)
    fx_sync_interval_seconds: int = Field(default=3600, ge=300)
    market_stale_after_seconds: int = Field(default=900, ge=60)
    market_history_retention_days: int = Field(default=7, ge=1)

    # Voryn AI. "disabled" (or a missing key) turns the assistant off gracefully.
    ai_provider: Literal["anthropic", "disabled"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    ai_model: str = "claude-opus-5-5"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ai_max_tokens: int = Field(default=64000, ge=1024)
    ai_max_tool_rounds: int = Field(default=8, ge=1, le=20)
    ai_messages_per_hour: int = Field(default=30, ge=1)
    ai_messages_per_day: int = Field(default=150, ge=1)
    #: History is append-only (never trimmed), so long chats are capped instead.
    ai_max_turns_per_conversation: int = Field(default=30, ge=2)

    sentry_dsn: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # Railway/Heroku style URLs omit the async driver.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value.removeprefix(prefix)
        return value

    @field_validator(
        "anthropic_api_key", "coingecko_api_key", "smtp_password", "sentry_dsn", mode="before"
    )
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        # docker compose passes unset optional variables as empty strings.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("encryption_keys", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_for_runtime(self) -> None:
        """Fail fast on insecure configuration in production."""
        if not self.is_production:
            return
        problems: list[str] = []
        secret = self.secret_key.get_secret_value()
        if secret.startswith("dev-only") or len(secret) < 32:
            problems.append("SECRET_KEY must be a random value with at least 32 characters")
        if not self.encryption_keys:
            problems.append("ENCRYPTION_KEYS must contain at least one Fernet key")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if self.email_backend != "smtp":
            problems.append("EMAIL_BACKEND must be smtp in production")
        if problems:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
