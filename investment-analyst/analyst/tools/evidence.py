"""Evidence registry stored in ADK session state + safe tool execution wrapper."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel

from ..data.schemas import Citation, EvidenceType

logger = logging.getLogger(__name__)

EVIDENCE_KEY = "evidence"


class _HasState(Protocol):
    state: Any


def record_evidence(
    tool_context: _HasState | None,
    *,
    citation_id: str,
    type: EvidenceType,  # noqa: A002 - mirrors the citation schema
    title: str,
    source: str,
    data: dict[str, Any],
    url: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Store an evidence record in session state and return the payload for the LLM."""
    record = {
        "citation": Citation(id=citation_id, type=type, title=title, source=source, url=url, as_of=as_of).model_dump(),
        "data": data,
    }
    if tool_context is not None:
        # Re-assign (never mutate in place) so ADK records a state delta.
        current = dict(tool_context.state.get(EVIDENCE_KEY) or {})
        current[citation_id] = record
        tool_context.state[EVIDENCE_KEY] = current
    return {"citation_id": citation_id, **data}


def get_evidence(state: Any) -> dict[str, dict[str, Any]]:
    return dict((state or {}).get(EVIDENCE_KEY) or {})


def dump(model: BaseModel, **exclude: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True, **exclude)


def safe_tool(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Convert any exception into a structured error the LLM can reason about.

    Tools must never crash the agent loop; the analyst is instructed to state that
    data was unavailable rather than guess.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            return {"error": str(exc), "error_type": "invalid_argument"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool failed", extra={"tool": fn.__name__, "error": repr(exc)})
            return {
                "error": f"Data unavailable from external providers: {exc}",
                "error_type": "data_unavailable",
                "instruction": "Do not estimate or invent this data. Tell the user it is unavailable.",
            }

    return wrapper
