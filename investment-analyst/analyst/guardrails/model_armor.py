"""GCP Model Armor integration (prompt + response sanitisation).

Enabled when ``MODEL_ARMOR_TEMPLATE=projects/P/locations/L/templates/T`` is set.
Fails *closed* for prompts flagged as MATCH_FOUND and fails *open* (with a warning)
if the Model Armor API itself is unreachable, so availability issues never take the
analyst tool down. Uses the regional REST endpoint with ADC credentials.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..config import get_settings
from ..data import http
from .injection import INJECTION_MESSAGE, Verdict

logger = logging.getLogger(__name__)

_TEMPLATE_RE = re.compile(r"^projects/[^/]+/locations/(?P<location>[^/]+)/templates/[^/]+$")
_MATCH_RE = re.compile(r"(?<!NO_)MATCH_FOUND")


def _access_token() -> str:  # pragma: no cover - requires ADC
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _endpoint(template: str, method: str) -> str:
    match = _TEMPLATE_RE.match(template)
    if not match:
        raise ValueError(f"Invalid MODEL_ARMOR_TEMPLATE: {template}")
    location = match.group("location")
    return f"https://modelarmor.{location}.rep.googleapis.com/v1/{template}:{method}"


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = http.get_client().post(
        url, json=body, headers={"Authorization": f"Bearer {_access_token()}"}, timeout=5.0
    )
    response.raise_for_status()
    return response.json()


def _flagged(result: dict[str, Any]) -> tuple[bool, list[str]]:
    sanitization = result.get("sanitizationResult") or {}
    matched = sanitization.get("filterMatchState") == "MATCH_FOUND"
    filters = []
    for name, item in (sanitization.get("filterResults") or {}).items():
        # Substring check must not count "NO_MATCH_FOUND" as a match.
        if _MATCH_RE.search(str(item)):
            filters.append(name)
    return matched, filters


def screen_prompt(text: str) -> Verdict:
    template = get_settings().model_armor_template
    if not template:
        return Verdict(blocked=False)
    try:
        result = _post(_endpoint(template, "sanitizeUserPrompt"), {"userPromptData": {"text": text}})
    except Exception:
        logger.warning("Model Armor unavailable; local guardrails only", exc_info=True)
        return Verdict(blocked=False)
    matched, filters = _flagged(result)
    if matched:
        return Verdict(True, "model_armor", f"filters: {','.join(filters) or 'unknown'}", INJECTION_MESSAGE)
    return Verdict(blocked=False)


def screen_response(text: str) -> Verdict:
    template = get_settings().model_armor_template
    if not template:
        return Verdict(blocked=False)
    try:
        result = _post(_endpoint(template, "sanitizeModelResponse"), {"modelResponseData": {"text": text}})
    except Exception:
        logger.warning("Model Armor unavailable for response screening", exc_info=True)
        return Verdict(blocked=False)
    matched, filters = _flagged(result)
    if matched:
        return Verdict(
            True,
            "model_armor_response",
            f"filters: {','.join(filters) or 'unknown'}",
            "The generated brief was withheld by the safety filter. Please rephrase your request.",
        )
    return Verdict(blocked=False)
