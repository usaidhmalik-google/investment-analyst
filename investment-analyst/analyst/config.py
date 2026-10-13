"""Runtime configuration loaded from environment variables (see docs/API_CONTRACT.md)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

STRATEGIES: tuple[str, ...] = ("momentum", "value", "swing", "income")


class Settings(BaseSettings):
    """Typed application settings. Every field maps to an upper-case env var."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # --- GCP / Vertex AI -------------------------------------------------------
    google_cloud_project: str | None = Field(default=None, alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(default="us-central1", alias="GOOGLE_CLOUD_LOCATION")

    # --- Models ---------------------------------------------------------------
    router_model: str = Field(default="gemini-3.5-flash", alias="ANALYST_ROUTER_MODEL")
    reasoning_model: str = Field(default="gemini-2.5-pro", alias="ANALYST_REASONING_MODEL")
    judge_model: str = Field(default="gemini-3.5-flash", alias="ANALYST_JUDGE_MODEL")

    # --- External data providers ---------------------------------------------
    alpha_vantage_secret: str | None = Field(default=None, alias="ALPHA_VANTAGE_SECRET")
    alpha_vantage_api_key: str | None = Field(default=None, alias="ALPHA_VANTAGE_API_KEY")
    sec_user_agent: str = Field(default="MALIK LLC Investment Analyst admin@malik-llc.example", alias="SEC_USER_AGENT")
    offline_mode: bool = Field(default=False, alias="ANALYST_OFFLINE_MODE")

    # --- Resilience & caching -------------------------------------------------
    http_timeout_seconds: float = Field(default=10.0, alias="HTTP_TIMEOUT_SECONDS")
    agent_timeout_seconds: float = Field(default=180.0, alias="AGENT_TIMEOUT_SECONDS")
    sse_heartbeat_seconds: float = Field(default=15.0, alias="SSE_HEARTBEAT_SECONDS")
    http_max_retries: int = Field(default=4, alias="HTTP_MAX_RETRIES")
    http_backoff_base_seconds: float = Field(default=0.5, alias="HTTP_BACKOFF_BASE_SECONDS")
    http_backoff_max_seconds: float = Field(default=8.0, alias="HTTP_BACKOFF_MAX_SECONDS")
    quote_cache_ttl_seconds: int = Field(default=30, alias="QUOTE_CACHE_TTL_SECONDS")
    data_cache_ttl_seconds: int = Field(default=900, alias="DATA_CACHE_TTL_SECONDS")
    sec_cache_ttl_seconds: int = Field(default=21600, alias="SEC_CACHE_TTL_SECONDS")

    # --- Conversation sessions -------------------------------------------------
    # memory: per-instance (dev). database: SQLAlchemy URL (e.g. Cloud SQL Postgres).
    # vertex: Vertex AI Agent Engine managed sessions (shared across Cloud Run instances).
    session_backend: Literal["memory", "database", "vertex"] = Field(default="memory", alias="SESSION_BACKEND")
    session_db_url: str | None = Field(default=None, alias="SESSION_DB_URL")
    agent_engine_id: str | None = Field(default=None, alias="AGENT_ENGINE_ID")

    # --- Persistence & telemetry ----------------------------------------------
    persistence_backend: Literal["memory", "firestore"] = Field(default="memory", alias="PERSISTENCE_BACKEND")
    firestore_database: str = Field(default="(default)", alias="FIRESTORE_DATABASE")
    firestore_collection: str = Field(default="analyst_reports", alias="FIRESTORE_COLLECTION")
    bq_usage_table: str | None = Field(default=None, alias="BQ_USAGE_TABLE")
    bq_audit_table: str | None = Field(default=None, alias="BQ_AUDIT_TABLE")
    enable_cloud_trace: bool = Field(default=False, alias="ENABLE_CLOUD_TRACE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Security ---------------------------------------------------------------
    require_iap: bool = Field(default=False, alias="REQUIRE_IAP")
    iap_audience: str | None = Field(default=None, alias="IAP_AUDIENCE")
    model_armor_template: str | None = Field(default=None, alias="MODEL_ARMOR_TEMPLATE")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"], alias="CORS_ORIGINS")

    # --- Prompts ---------------------------------------------------------------
    prompt_version: str = Field(default="v1", alias="PROMPT_VERSION")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
