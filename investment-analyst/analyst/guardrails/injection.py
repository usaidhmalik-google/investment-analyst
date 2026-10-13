"""Local, zero-latency input screening for prompt injection and out-of-scope requests.

This runs before any model call. It complements (not replaces) GCP Model Armor,
which is applied when ``MODEL_ARMOR_TEMPLATE`` is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_PROMPT_CHARS = 4000


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    category: str | None = None
    reason: str | None = None
    message: str | None = None


ALLOW = Verdict(blocked=False)

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+|any\s+|your\s+)?(previous|prior|system)?\s*(instructions|rules|guidelines)",
    r"(reveal|show|print|repeat|output|leak)\s+(me\s+)?(your|the)\s+(system\s+prompt|instructions|hidden\s+prompt|initial\s+prompt)",
    r"\b(system\s+prompt|developer\s+message)\b.*\b(reveal|show|print|dump)\b",
    r"\byou\s+are\s+now\s+(dan|in\s+developer\s+mode|jailbroken|unrestricted)\b",
    r"\bjailbreak\b",
    r"\b(api[_\s-]?key|credentials?|service\s+account\s+key|secret\s+manager)\b.*\b(show|give|print|reveal|tell)\b",
    r"\b(show|give|print|reveal|tell)\b.*\b(api[_\s-]?key|credentials?|password|access\s+token|service\s+account\s+key)\b",
    r"<\s*/?\s*(system|assistant)\s*>",
    r"pretend\s+(that\s+)?you\s+(have\s+)?no\s+(rules|restrictions|guardrails)",
]

_TRADING_PATTERNS = [
    r"\b(buy|sell|short|purchase|liquidate)\s+(?:(?:\d+|some|all|my)\s*){0,2}(shares?|stocks?|positions?|options?|contracts?)\b.*\b(for\s+me|now|immediately|on\s+my\s+account)\b",
    r"\b(place|execute|submit|route)\s+(a|an|the)?\s*(trade|order|buy\s+order|sell\s+order|market\s+order|limit\s+order)\b",
    r"\b(rebalance|transfer\s+funds?\s+in)\s+my\s+(portfolio|account)\b",
]

_COMPILED_INJECTION = [re.compile(p, re.I | re.S) for p in _INJECTION_PATTERNS]
_COMPILED_TRADING = [re.compile(p, re.I | re.S) for p in _TRADING_PATTERNS]

INJECTION_MESSAGE = (
    "I can't help with that request. I'm limited to grounded public-market research — quotes, news, "
    "SEC filings and strategy evaluations — and I can't change or disclose my operating instructions."
)
TRADING_MESSAGE = (
    "I can't execute trades or manage portfolios. I can research the company, summarise filings and news, "
    "or evaluate it against a Momentum, Value, Swing or Income strategy to inform your own decision."
)
LENGTH_MESSAGE = f"Your message is too long. Please keep requests under {MAX_PROMPT_CHARS} characters."


def screen_prompt(text: str) -> Verdict:
    """Return a blocking verdict for injection attempts, trade-execution requests or oversize input."""
    if len(text) > MAX_PROMPT_CHARS:
        return Verdict(True, "input_length", "prompt exceeds maximum length", LENGTH_MESSAGE)
    for pattern in _COMPILED_INJECTION:
        if pattern.search(text):
            return Verdict(True, "prompt_injection", f"matched pattern: {pattern.pattern[:60]}", INJECTION_MESSAGE)
    for pattern in _COMPILED_TRADING:
        if pattern.search(text):
            return Verdict(True, "trade_execution", f"matched pattern: {pattern.pattern[:60]}", TRADING_MESSAGE)
    return ALLOW
