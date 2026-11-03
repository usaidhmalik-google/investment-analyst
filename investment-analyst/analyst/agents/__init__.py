"""Multi-agent topology (Google ADK).

    root_orchestrator (router model)
      ├── data_gatherer       [single_turn sub-agent → exposed as a tool]
      ├── sec_filing_parser   [single_turn sub-agent → exposed as a tool]
      ├── strategy_evaluator  [single_turn sub-agent → exposed as a tool]
      └── financial_analyst   [chat sub-agent → reached via transfer_to_agent, streams the brief]

Specialists run inline in the parent session, so the evidence they record in session
state is immediately visible to the Financial Analyst's instruction provider. The
analyst cannot transfer back, so every new user turn starts at the orchestrator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm import BaseLlm
from google.genai import types

from ..config import Settings, get_settings
from ..prompts import render_prompt
from ..tools.evidence import get_evidence
from ..tools.market_tools import DATA_GATHERER_TOOLS
from ..tools.sec_tools import SEC_FILING_TOOLS
from ..tools.strategy_tools import STRATEGY_TOOLS
from .callbacks import input_guardrail

ROOT_AGENT_NAME = "root_orchestrator"
DATA_GATHERER = "data_gatherer"
SEC_FILING_PARSER = "sec_filing_parser"
STRATEGY_EVALUATOR = "strategy_evaluator"
FINANCIAL_ANALYST = "financial_analyst"
STRATEGY_STATE_KEY = "strategy_preference"

ModelRef = str | BaseLlm


@dataclass
class AgentModels:
    """Model assignment per agent (TDD: Flash for routing, Pro for financial reasoning)."""

    orchestrator: ModelRef
    data_gatherer: ModelRef
    sec_filing_parser: ModelRef
    strategy_evaluator: ModelRef
    financial_analyst: ModelRef

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentModels:
        router = settings.router_model
        return cls(router, router, router, router, settings.reasoning_model)


def _today() -> str:
    return date.today().isoformat()


def _strategy(ctx: ReadonlyContext) -> str:
    return str(ctx.state.get(STRATEGY_STATE_KEY) or "none selected")


def evidence_for_prompt(state: Any) -> str:
    evidence = get_evidence(state)
    if not evidence:
        return "{}"
    compact = {cid: {**record["citation"], "data": record["data"]} for cid, record in evidence.items()}
    return json.dumps(compact, separators=(",", ":"), ensure_ascii=False, default=str)


def _provider(name: str, version: str, with_evidence: bool = False):
    def instruction(ctx: ReadonlyContext) -> str:
        values = {"today": _today(), "strategy": _strategy(ctx)}
        if with_evidence:
            values["evidence"] = evidence_for_prompt(ctx.state)
        return render_prompt(name, version, **values)

    instruction.__name__ = f"{name}_instruction"
    return instruction


def _cfg(temperature: float, max_tokens: int) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens)


def build_root_agent(settings: Settings | None = None, models: AgentModels | None = None) -> LlmAgent:
    """Construct a fresh agent tree. ``models`` lets tests inject scripted fake LLMs."""
    settings = settings or get_settings()
    models = models or AgentModels.from_settings(settings)
    version = settings.prompt_version

    specialist_kwargs: dict[str, Any] = {
        "mode": "single_turn",
        "disallow_transfer_to_parent": True,
        "disallow_transfer_to_peers": True,
        "generate_content_config": _cfg(0.0, 1024),
    }
    data_gatherer = LlmAgent(
        name=DATA_GATHERER,
        description=(
            "Fetches deterministic market data: real-time quotes, price history/performance windows, "
            "fundamentals and the latest news for one or more tickers."
        ),
        model=models.data_gatherer,
        instruction=_provider("data_gatherer", version),
        tools=list(DATA_GATHERER_TOOLS),
        **specialist_kwargs,
    )
    sec_filing_parser = LlmAgent(
        name=SEC_FILING_PARSER,
        description=(
            "Retrieves SEC EDGAR filings (10-K, 10-Q, 8-K, proxy, Form 4, 13F), extracts sections such as "
            "risk factors and MD&A, and returns XBRL-reported financials."
        ),
        model=models.sec_filing_parser,
        instruction=_provider("sec_filing_parser", version),
        tools=list(SEC_FILING_TOOLS),
        **specialist_kwargs,
    )
    strategy_evaluator = LlmAgent(
        name=STRATEGY_EVALUATOR,
        description=(
            "Runs deterministic Momentum, Value, Swing or Income strategy evaluations for tickers and "
            "returns the signal, score and indicator values."
        ),
        model=models.strategy_evaluator,
        instruction=_provider("strategy_evaluator", version),
        tools=list(STRATEGY_TOOLS),
        **specialist_kwargs,
    )
    financial_analyst = LlmAgent(
        name=FINANCIAL_ANALYST,
        description=(
            "Synthesises the collected evidence into a grounded, fully cited investment brief. Transfer here "
            "after the specialists have gathered data."
        ),
        model=models.financial_analyst,
        instruction=_provider("financial_analyst", version, with_evidence=True),
        generate_content_config=_cfg(0.2, 4096),
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )
    return LlmAgent(
        name=ROOT_AGENT_NAME,
        description="Routes analyst requests to specialist agents and hands synthesis to the Financial Analyst.",
        model=models.orchestrator,
        instruction=_provider("orchestrator", version),
        generate_content_config=_cfg(0.0, 1024),
        sub_agents=[data_gatherer, sec_filing_parser, strategy_evaluator, financial_analyst],
        before_model_callback=input_guardrail,
    )
