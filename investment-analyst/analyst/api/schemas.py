"""HTTP API request/response models (mirrors docs/API_CONTRACT.md)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..data.schemas import Citation
from ..guardrails.fact_check import FactCheckResult

StrategyName = Literal["momentum", "value", "swing", "income"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")
    strategy: StrategyName | None = None

    @field_validator("message")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class ToolCall(BaseModel):
    agent: str
    tool: str
    args: dict = Field(default_factory=dict)


class Latency(BaseModel):
    time_to_first_thought_ms: float | None = None
    time_to_first_token_ms: float | None = None
    total_ms: float


class Usage(BaseModel):
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    report_id: str
    session_id: str
    response: str
    citations: list[Citation] = Field(default_factory=list)
    fact_check: FactCheckResult
    tools_called: list[ToolCall] = Field(default_factory=list)
    latency: Latency
    usage: Usage = Field(default_factory=Usage)
    blocked: bool = False
    block_reason: str | None = None


class FeedbackRequest(BaseModel):
    report_id: str = Field(min_length=1, max_length=64)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


class ConfigResponse(BaseModel):
    strategies: list[str]
    models: dict[str, str]
    offline_mode: bool
    prompt_version: str
