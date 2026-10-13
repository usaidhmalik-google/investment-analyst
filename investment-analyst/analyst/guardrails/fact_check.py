"""Post-generation fact checking: every number in the narrative must trace to evidence.

Implements the TDD "Fact Checks" guardrail and the North Star accuracy metric
(100% agreement between narrative numbers and deterministic API outputs). A number in
the brief *matches* when it equals some evidence value within the rounding precision
implied by how it is written (e.g. ``$3.15T`` matches 3,151,234,567,890).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field

_SCALES = {
    "t": 1e12, "tn": 1e12, "trillion": 1e12,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "m": 1e6, "mm": 1e6, "million": 1e6,
    "k": 1e3, "thousand": 1e3,
}  # fmt: skip

NUMBER_RE = re.compile(
    r"""
    (?<![\w.])
    (?P<neg>[-−])?
    (?P<cur>\$)?
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    (?:\s?(?P<suffix>(?i:trillion|billion|million|thousand|tn|bn|mm)\b|[TBMK](?![A-Za-z])))?
    (?P<pct>\s?%|\s?(?i:percent)\b|\s?(?i:pp)\b)?
    (?P<x>x(?![A-Za-z]))?
    """,
    re.X,
)

# Spans that contain digits but are not financial figures.
_STRIP_PATTERNS = [
    r"\[[^\]\n]{1,120}\]",  # citations
    r"\]\([^)]+\)",  # markdown link targets
    r"https?://\S+",
    r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.+\-Z]+)?\b",  # ISO dates
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?(?:\s+\d{4})?",
    r"\b(?:10-K|10-Q|8-K|13F(?:-HR)?|DEF\s?14A|S-1|20-F|6-K)(?:/A)?\b",
    r"\bForm\s+\d+\b",
    r"\bItem\s+\d+[A-C]?(?:\.\d{2})?\b",
    r"\b\d+\s?[- ](?:day|week|month|year|quarter|yr|session|bar)s?\b",
    r"\b\d+(?:d|mo|y|yr|w)\b",
    r"\b(?:RSI|SMA|EMA|ATR|MACD|ROC|Bollinger(?:\s+Bands?)?)\s*\([\d,\s.]+\)",
    r"\b(?:RSI|SMA|EMA|ATR|ROC)[-_]?\d+\b",
    r"\b(?:SMA|EMA)\s\d{1,3}\b(?!\.\d)",  # "SMA 50" names the window, not a value
    r"\b(?:Q[1-4]|H[12])\s?(?:FY)?\s?'?\d{0,4}\b",
    r"\bFY\s?'?\d{2,4}\b",
    r"\b\d+(?:st|nd|rd|th)\b",
    r"\bGemini\s+[\d.]+",
    r"\b[A-Z]{1,5}:\w+(?::[\w.-]+)*\b",  # stray citation ids without brackets
]
_STRIP_RE = re.compile("|".join(f"(?:{p})" for p in _STRIP_PATTERNS), re.I)


class NumberToken(BaseModel):
    text: str
    value: float
    decimals: int
    scale: float
    is_percent: bool


class FactCheckResult(BaseModel):
    verified: bool
    checked_numbers: int
    matched_numbers: int
    unverified_numbers: list[str] = Field(default_factory=list)
    accuracy: float


def _parse(match: re.Match[str]) -> NumberToken | None:
    raw = match.group("num").replace(",", "")
    try:
        base = float(raw)
    except ValueError:
        return None
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    suffix = (match.group("suffix") or "").lower()
    scale = _SCALES.get(suffix, 1.0)
    neg = -1 if match.group("neg") else 1
    return NumberToken(
        text=match.group(0).strip(),
        value=neg * base * scale,
        decimals=decimals,
        scale=scale,
        is_percent=bool(match.group("pct")),
    )


def extract_numbers(text: str, *, skip_trivial: bool = True) -> list[NumberToken]:
    """Extract financial figures from narrative text (citations, dates, form names removed)."""
    cleaned = _STRIP_RE.sub(" ", text)
    tokens: list[NumberToken] = []
    for match in NUMBER_RE.finditer(cleaned):
        token = _parse(match)
        if token is None:
            continue
        bare = not (match.group("cur") or match.group("suffix") or match.group("pct") or match.group("x"))
        if skip_trivial and bare:
            if token.decimals == 0 and abs(token.value) <= 10:
                continue  # list numbering, counts, scores
            if token.decimals == 0 and 1900 <= token.value <= 2100 and "," not in match.group("num"):
                continue  # years (comma-formatted counts like "2,050" are still checked)
        tokens.append(token)
    return tokens


def _walk_numbers(obj: Any) -> Iterable[float]:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        if not (isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj))):
            yield float(obj)
    elif isinstance(obj, str):
        for token in extract_numbers(obj, skip_trivial=False):
            yield token.value
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _walk_numbers(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _walk_numbers(value)


def evidence_numbers(evidence: dict[str, dict[str, Any]]) -> list[float]:
    values: set[float] = set()
    for record in evidence.values():
        values.update(_walk_numbers(record.get("data", record)))
    return sorted(values)


def _matches(token: NumberToken, candidates: list[float]) -> bool:
    tolerance = 0.5 * (10 ** (-token.decimals)) * token.scale
    target = abs(token.value)
    for candidate in candidates:
        eps = 1e-9 * max(abs(candidate), 1.0)
        if abs(target - abs(candidate)) <= tolerance + eps:
            return True
    return False


def fact_check(narrative: str, evidence: dict[str, dict[str, Any]]) -> FactCheckResult:
    """Verify each figure in ``narrative`` against the numeric universe of ``evidence``."""
    tokens = extract_numbers(narrative)
    if not tokens:
        return FactCheckResult(verified=True, checked_numbers=0, matched_numbers=0, accuracy=1.0)
    candidates = evidence_numbers(evidence)
    unverified = [t.text for t in tokens if not _matches(t, candidates)]
    matched = len(tokens) - len(unverified)
    return FactCheckResult(
        verified=not unverified,
        checked_numbers=len(tokens),
        matched_numbers=matched,
        unverified_numbers=list(dict.fromkeys(unverified)),
        accuracy=round(matched / len(tokens), 4),
    )


CITATION_RE = re.compile(r"\[((?:Q|H|M|N|SEC|XBRL|S):[A-Za-z0-9.\-:_]+)\]")


def cited_ids(narrative: str) -> list[str]:
    """Return citation ids referenced in the narrative, in first-seen order."""
    return list(dict.fromkeys(CITATION_RE.findall(narrative)))
