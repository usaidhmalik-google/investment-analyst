"""ADK callbacks shared by the agent tree (input guardrails)."""

from __future__ import annotations

import logging

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from ..guardrails import injection, model_armor

logger = logging.getLogger(__name__)


def _latest_user_text(llm_request: LlmRequest) -> str | None:
    """Return the user's text if the request was triggered by a fresh user message."""
    if not llm_request.contents:
        return None
    last = llm_request.contents[-1]
    if last.role != "user" or not last.parts:
        return None
    if any(p.function_response for p in last.parts):
        return None
    texts = [p.text for p in last.parts if p.text]
    return "\n".join(texts) if texts else None


def input_guardrail(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse | None:
    """Block prompt injection / trade execution before the orchestrator model is called."""
    text = _latest_user_text(llm_request)
    if not text:
        return None
    verdict = injection.screen_prompt(text)
    if not verdict.blocked:
        verdict = model_armor.screen_prompt(text)
    if not verdict.blocked:
        return None
    logger.warning("input blocked by guardrail", extra={"category": verdict.category, "reason": verdict.reason})
    callback_context.state["temp:blocked_category"] = verdict.category
    return LlmResponse(content=types.Content(role="model", parts=[types.Part.from_text(text=verdict.message or "")]))
