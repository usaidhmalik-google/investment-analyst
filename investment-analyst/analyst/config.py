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
    # Vertex AI endpoint for Gemini calls; Gemini 3.x is served from `global`.
    google_cloud_location: str = Field(default="global", alias="GOOGLE_CLOUD_LOCATION")

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
    # Agent Engine is regional, while Gemini 3.x models are served from the `global` endpoint.
    agent_engine_location: str = Field(default="us-central1", alias="AGENT_ENGINE_LOCATION")

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

    # --- Feature flags, experimentation & extensibility ------------------------
    enable_dlp_redaction: bool = Field(default=True, alias="ENABLE_DLP_REDACTION")
    enable_hybrid_rag: bool = Field(default=True, alias="ENABLE_HYBRID_RAG")
    experiment_id: str = Field(default="exp-model-tiering-v1", alias="EXPERIMENT_ID")
    experiment_variant: str = Field(default="control", alias="EXPERIMENT_VARIANT")
    webhook_target_url: str = Field(default="", alias="WEBHOOK_TARGET_URL")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")

    def feature_flags(self) -> dict[str, bool]:
        return {
            "dlp_redaction": self.enable_dlp_redaction,
            "hybrid_rag": self.enable_hybrid_rag,
            "offline_mode": self.offline_mode,
            "cloud_trace": self.enable_cloud_trace,
            "model_armor": bool(self.model_armor_template),
        }


# Vertex AI published list pricing (USD per 1M tokens)
FLASH_INPUT_USD_PER_1M = 0.15
FLASH_OUTPUT_USD_PER_1M = 0.60
PRO_INPUT_USD_PER_1M = 1.25
PRO_OUTPUT_USD_PER_1M = 10.00


def estimate_turn_cost_usd(
    prompt_tokens: int,
    output_tokens: int,
    *,
    pro_share: float = 0.35,
) -> float:
    """Estimate turn cost in USD using the tiered Flash (router/specialists) + Pro (analyst) blend."""
    p_tok = max(0, int(prompt_tokens))
    o_tok = max(0, int(output_tokens))
    pro_w = max(0.0, min(1.0, float(pro_share)))
    flash_w = 1.0 - pro_w
    blended_in = flash_w * FLASH_INPUT_USD_PER_1M + pro_w * PRO_INPUT_USD_PER_1M
    blended_out = flash_w * FLASH_OUTPUT_USD_PER_1M + pro_w * PRO_OUTPUT_USD_PER_1M
    cost = (p_tok * blended_in + o_tok * blended_out) / 1_000_000.0
    return round(cost, 6)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
