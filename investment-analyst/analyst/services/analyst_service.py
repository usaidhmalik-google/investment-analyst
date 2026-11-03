"""Orchestrates one analyst turn: guardrails → ADK multi-agent run → fact check → persistence.

Converts raw ADK events into the SSE event stream defined in docs/API_CONTRACT.md and
captures latency (time to first thought / first token / total), token usage and the
tool-call audit trail.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types
from opentelemetry import trace

from ..agents import FINANCIAL_ANALYST, ROOT_AGENT_NAME, STRATEGY_STATE_KEY, build_root_agent
from ..api.schemas import ChatRequest, ChatResponse, Latency, ToolCall, Usage
from ..config import Settings
from ..data.schemas import Citation
from ..guardrails import injection, model_armor
from ..guardrails.fact_check import FactCheckResult, cited_ids, fact_check
from ..prompts import prompt_fingerprint
from ..tools.evidence import get_evidence
from .report_store import ReportStore
from .sessions import build_session_service
from .telemetry_sink import TelemetrySink

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("analyst.service")

APP_NAME = "investment_analyst"
_NARRATIVE_AUTHORS = {ROOT_AGENT_NAME, FINANCIAL_ANALYST}
_DETAIL_KEYS = ("ticker", "period", "strategy", "form_type", "section", "form_types", "limit")


@dataclass
class StreamEvent:
    type: str
    data: dict[str, Any]


@dataclass
class UserIdentity:
    user_id: str
    email: str | None = None


@dataclass
class _TurnState:
    started: float
    first_thought: float | None = None
    first_token: float | None = None
    final_text: str = ""
    streamed_partial: bool = False
    tools: list[ToolCall] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    error: str | None = None


def _detail(args: dict[str, Any]) -> str:
    if "request" in args:
        text = str(args["request"])
        return text if len(text) <= 160 else text[:157] + "..."
    parts = [f"{k}={args[k]}" for k in _DETAIL_KEYS if k in args and args[k] not in (None, "")]
    return ", ".join(parts)


class AnalystService:
    def __init__(
        self,
        settings: Settings,
        store: ReportStore,
        telemetry: TelemetrySink,
        agent: LlmAgent | None = None,
        session_service: BaseSessionService | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.telemetry = telemetry
        self.agent = agent or build_root_agent(settings)
        self.session_service = session_service or build_session_service(settings)
        self.runner = Runner(app_name=APP_NAME, agent=self.agent, session_service=self.session_service)
        self.prompt_lineage = {
            name: prompt_fingerprint(name, settings.prompt_version) for name in ("orchestrator", "financial_analyst")
        }

    # ------------------------------------------------------------------ helpers

    def _ms(self, start: float, end: float | None) -> float | None:
        return None if end is None else round((end - start) * 1000, 1)

    async def _session(self, user: UserIdentity, session_id: str | None):
        if session_id:
            existing = await self.session_service.get_session(
                app_name=APP_NAME, user_id=user.user_id, session_id=session_id
            )
            if existing is not None:
                return existing
        # Unknown or foreign ids are never adopted: the server always mints the id (also required by
        # Vertex AI Agent Engine sessions) and returns it in the `session` event.
        session_kwargs = {} if self.settings.session_backend == "vertex" else {"session_id": uuid.uuid4().hex}
        return await self.session_service.create_session(app_name=APP_NAME, user_id=user.user_id, **session_kwargs)

    def _handle_event(self, event: Event, turn: _TurnState) -> list[StreamEvent]:
        now = time.perf_counter()
        out: list[StreamEvent] = []
        if event.error_message:
            turn.error = event.error_message
        if event.usage_metadata and not event.partial:
            um = event.usage_metadata
            turn.usage.prompt_tokens += um.prompt_token_count or 0
            turn.usage.output_tokens += um.candidates_token_count or 0
            turn.usage.total_tokens += um.total_token_count or 0
        parts = event.content.parts if event.content and event.content.parts else []
        for part in parts:
            if part.function_call and not event.partial:
                fc = part.function_call
                args = dict(fc.args or {})
                if turn.first_thought is None:
                    turn.first_thought = now
                if fc.name == "transfer_to_agent":
                    out.append(
                        self._thought(turn, now, event.author, "agent_transfer", str(args.get("agent_name")), "")
                    )
                    continue
                turn.tools.append(ToolCall(agent=event.author, tool=fc.name, args=args))
                ticker = args.get("ticker")
                if isinstance(ticker, str) and ticker.upper() not in turn.tickers:
                    turn.tickers.append(ticker.upper())
                out.append(self._thought(turn, now, event.author, "tool_call", fc.name, _detail(args)))
            elif part.function_response and not event.partial:
                fr = part.function_response
                if fr.name == "transfer_to_agent":
                    continue
                response = fr.response or {}
                error = response.get("error") if isinstance(response, dict) else None
                detail = f"error: {error}" if error else "ok"
                out.append(self._thought(turn, now, event.author, "tool_result", fr.name, detail))

        narrative = "".join(p.text for p in parts if p.text and not p.thought)
        if narrative and event.author in _NARRATIVE_AUTHORS and not event.branch:
            if turn.first_thought is None:
                turn.first_thought = now
            if event.partial:
                if turn.first_token is None:
                    turn.first_token = now
                turn.streamed_partial = True
                out.append(StreamEvent("token", {"agent": event.author, "text": narrative}))
            else:
                if not turn.streamed_partial:  # non-streaming model: emit the whole message once
                    if turn.first_token is None:
                        turn.first_token = now
                    out.append(StreamEvent("token", {"agent": event.author, "text": narrative}))
                turn.final_text = narrative  # the last complete narrative message is the answer
                turn.streamed_partial = False
        return out

    def _thought(self, turn: _TurnState, now: float, agent: str, kind: str, name: str, detail: str) -> StreamEvent:
        return StreamEvent(
            "thought",
            {"agent": agent, "kind": kind, "name": name, "detail": detail, "elapsed_ms": self._ms(turn.started, now)},
        )

    # ------------------------------------------------------------------ main entry points

    async def stream(self, request: ChatRequest, user: UserIdentity) -> AsyncIterator[StreamEvent]:
        turn = _TurnState(started=time.perf_counter())
        report_id = uuid.uuid4().hex
        session = await self._session(user, request.session_id)
        yield StreamEvent("session", {"session_id": session.id})

        with tracer.start_as_current_span("analyst.turn") as span:
            span.set_attribute("analyst.session_id", session.id)
            span.set_attribute("analyst.report_id", report_id)
            span.set_attribute("analyst.strategy", request.strategy or "none")

            verdict = injection.screen_prompt(request.message)
            if not verdict.blocked:
                verdict = await asyncio.to_thread(model_armor.screen_prompt, request.message)
            if verdict.blocked:
                span.set_attribute("analyst.blocked", verdict.category or "blocked")
                response = self._build_response(
                    report_id, session.id, verdict.message or "", {}, turn, blocked=True, reason=verdict.category
                )
                await self._finalize(request, user, response, status="blocked")
                yield StreamEvent("final", response.model_dump(mode="json"))
                return

            state_delta = {STRATEGY_STATE_KEY: request.strategy} if request.strategy else None
            message = types.Content(role="user", parts=[types.Part.from_text(text=request.message)])
            run_config = RunConfig(streaming_mode=StreamingMode.SSE, max_llm_calls=30)
            try:
                async with asyncio.timeout(self.settings.agent_timeout_seconds):
                    async for event in self.runner.run_async(
                        user_id=user.user_id,
                        session_id=session.id,
                        new_message=message,
                        state_delta=state_delta,
                        run_config=run_config,
                    ):
                        for out in self._handle_event(event, turn):
                            yield out
            except TimeoutError:
                turn.error = "The analysis timed out. Please narrow the request and try again."
            except Exception as exc:
                logger.exception("agent run failed")
                turn.error = f"Agent execution failed: {type(exc).__name__}"

            if turn.error and not turn.final_text:
                span.set_attribute("analyst.error", turn.error)
                self.telemetry.record_audit(
                    user=user.email or user.user_id, action="chat", tickers=turn.tickers,
                    session_id=session.id, report_id=None, status="error",
                )  # fmt: skip
                yield StreamEvent("error", {"code": "agent_error", "message": turn.error})
                return

            refreshed = await self.session_service.get_session(
                app_name=APP_NAME, user_id=user.user_id, session_id=session.id
            )
            evidence = get_evidence(refreshed.state if refreshed else {})
            text = turn.final_text.strip()
            blocked_reason = None
            response_verdict = await asyncio.to_thread(model_armor.screen_response, text)
            if response_verdict.blocked:
                text, blocked_reason = response_verdict.message or "", response_verdict.category
            response = self._build_response(
                report_id, session.id, text, evidence, turn,
                blocked=response_verdict.blocked, reason=blocked_reason,
            )  # fmt: skip
            span.set_attribute("analyst.fact_check.accuracy", response.fact_check.accuracy)
            span.set_attribute("analyst.tools_called", len(response.tools_called))
            await self._finalize(request, user, response, status="ok")
            yield StreamEvent("final", response.model_dump(mode="json"))

    async def run(self, request: ChatRequest, user: UserIdentity) -> ChatResponse:
        final: dict[str, Any] | None = None
        async for event in self.stream(request, user):
            if event.type == "final":
                final = event.data
            elif event.type == "error":
                raise RuntimeError(event.data["message"])
        assert final is not None
        return ChatResponse.model_validate(final)

    # ------------------------------------------------------------------ response assembly

    def _build_response(
        self,
        report_id: str,
        session_id: str,
        text: str,
        evidence: dict[str, dict[str, Any]],
        turn: _TurnState,
        *,
        blocked: bool,
        reason: str | None,
    ) -> ChatResponse:
        end = time.perf_counter()
        if blocked:
            check = FactCheckResult(verified=True, checked_numbers=0, matched_numbers=0, accuracy=1.0)
            citations: list[Citation] = []
        else:
            check = fact_check(text, evidence)
            citations = [
                Citation.model_validate(evidence[cid]["citation"]) for cid in cited_ids(text) if cid in evidence
            ]
        return ChatResponse(
            report_id=report_id,
            session_id=session_id,
            response=text,
            citations=citations,
            fact_check=check,
            tools_called=turn.tools,
            latency=Latency(
                time_to_first_thought_ms=self._ms(turn.started, turn.first_thought),
                time_to_first_token_ms=self._ms(turn.started, turn.first_token),
                total_ms=self._ms(turn.started, end) or 0.0,
            ),
            usage=turn.usage,
            blocked=blocked,
            block_reason=reason,
        )

    async def _finalize(self, request: ChatRequest, user: UserIdentity, response: ChatResponse, status: str) -> None:
        tickers = sorted({t.args.get("ticker", "").upper() for t in response.tools_called if t.args.get("ticker")})
        user_label = user.email or user.user_id
        try:
            await self.store.save_report(
                {
                    "report_id": response.report_id,
                    "session_id": response.session_id,
                    "user": user_label,
                    "prompt": request.message,
                    "strategy": request.strategy,
                    "response_markdown": response.response,
                    "citations": [c.model_dump() for c in response.citations],
                    "fact_check": response.fact_check.model_dump(),
                    "tools_called": [t.model_dump() for t in response.tools_called],
                    "tickers": tickers,
                    "latency": response.latency.model_dump(),
                    "usage": response.usage.model_dump(),
                    "blocked": response.blocked,
                    "block_reason": response.block_reason,
                    "models": {"router": self.settings.router_model, "reasoning": self.settings.reasoning_model},
                    "prompt_version": self.settings.prompt_version,
                    "prompt_lineage": self.prompt_lineage,
                    "feedback": None,
                }
            )
        except Exception:
            logger.exception("failed to persist report", extra={"report_id": response.report_id})
        self.telemetry.record_usage(
            session_id=response.session_id,
            report_id=response.report_id,
            user=user_label,
            model=f"{self.settings.router_model}+{self.settings.reasoning_model}",
            agent=ROOT_AGENT_NAME,
            usage=response.usage.model_dump(),
            ttft_ms=response.latency.time_to_first_token_ms,
            total_ms=response.latency.total_ms,
            tools_called=[t.model_dump() for t in response.tools_called],
            tickers=tickers,
        )
        self.telemetry.record_audit(
            user=user_label,
            action="chat",
            tickers=tickers,
            session_id=response.session_id,
            report_id=response.report_id,
            status=status,
        )
