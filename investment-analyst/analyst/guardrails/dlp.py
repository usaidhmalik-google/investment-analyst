"""Data Loss Prevention (DLP), PII redaction, and data classification guardrails.

Provides deterministic pre-ingestion and pre-persistence PII/credential detection,
redaction, and data classification tagging aligned with FINRA Rule 3110 / SEC Reg S-P /
SOC2 / GDPR data-minimization controls.

Carefully tuned so financial figures (dollar amounts, percentages, dates, CIKs, and
18-digit SEC accession numbers such as ``0000320193-25-000079``) are never false-positived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


class DataClassification:
    """Enterprise data classification tiers."""

    PUBLIC_MARKET_DATA = "PUBLIC_MARKET_DATA"
    INTERNAL_ANALYST_WORK_PRODUCT = "INTERNAL_ANALYST_WORK_PRODUCT"
    CONFIDENTIAL_CLIENT_CONTEXT = "CONFIDENTIAL_CLIENT_CONTEXT"
    RESTRICTED_PII_OR_CREDENTIAL = "RESTRICTED_PII_OR_CREDENTIAL"


@dataclass(frozen=True)
class DLPFinding:
    category: str
    redacted_token: str
    count: int


@dataclass(frozen=True)
class DLPScanResult:
    sanitized_text: str
    has_pii: bool
    classification: str
    findings: list[DLPFinding] = field(default_factory=list)

    @property
    def categories(self) -> list[str]:
        return [f.category for f in self.findings]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "has_pii": self.has_pii,
            "redacted_categories": self.categories,
            "redacted_count": sum(f.count for f in self.findings),
        }


# --- Deterministic detectors ---

# US SSN: XXX-XX-XXXX (excluding invalid prefixes 000, 666, 900-999 and SEC accession substrings)
_SSN_RE = re.compile(
    r"(?<![\d\-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d\-])"
)

# API keys, Bearer tokens, Google API keys, OpenAI-style keys, GitHub PATs
_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{35}|ghp_[A-Za-z0-9]{30,})"
    r"|(?i:\bBearer\s+[A-Za-z0-9\-._~+/]{20,}=*)"
)

# Email addresses
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b"
)

# Explicit brokerage / bank account or routing numbers
_ACCOUNT_RE = re.compile(
    r"(?i)\b(?:account|acct|routing|iban)\s*(?:number|num|no|#)?\s*[:=#]?\s*[A-Z0-9\-]{8,22}\b"
)

# North American / international phone numbers with explicit formatting
# Avoids matching dates (YYYY-MM-DD) or SEC accession numbers (10-2-6 digits).
_PHONE_RE = re.compile(
    r"(?<![\d\-])(?:\+1[\s.\-]?)?(?:\([2-9]\d{2}\)[\s.\-]?|[2-9]\d{2}[\s.\-])[2-9]\d{2}[\s.\-]\d{4}(?![\d\-])"
)

# Candidate 13-to-19 digit payment card numbers (validated with Luhn checksum)
_CARD_CANDIDATE_RE = re.compile(
    r"(?<![\d\-])(?:\d{4}[\s\-]?){3}\d{1,7}(?![\d\-])"
)


def _passes_luhn(digits: str) -> bool:
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    if len(set(digits)) == 1:
        return False
    total = 0
    reverse_digits = digits[::-1]
    for idx, ch in enumerate(reverse_digits):
        n = int(ch)
        if idx % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def scan_and_redact(
    text: str,
    *,
    default_classification: str = DataClassification.INTERNAL_ANALYST_WORK_PRODUCT,
) -> DLPScanResult:
    """Scan *text* for PII or credentials and return a redacted copy plus classification metadata."""
    if not text:
        return DLPScanResult(
            sanitized_text=text,
            has_pii=False,
            classification=default_classification,
            findings=[],
        )

    sanitized = text
    findings: list[DLPFinding] = []

    patterns: list[tuple[str, re.Pattern[str], str]] = [
        ("CREDENTIAL_SECRET", _SECRET_RE, "[REDACTED:SECRET]"),
        ("US_SSN", _SSN_RE, "[REDACTED:SSN]"),
        ("EMAIL_ADDRESS", _EMAIL_RE, "[REDACTED:EMAIL]"),
        ("ACCOUNT_NUMBER", _ACCOUNT_RE, "[REDACTED:ACCOUNT_NUMBER]"),
        ("PHONE_NUMBER", _PHONE_RE, "[REDACTED:PHONE]"),
    ]

    for category, pattern, token in patterns:
        sanitized, count = pattern.subn(token, sanitized)
        if count > 0:
            findings.append(DLPFinding(category=category, redacted_token=token, count=count))

    # Credit card scan with Luhn check
    card_count = 0

    def _replace_card(match: re.Match[str]) -> str:
        nonlocal card_count
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if _passes_luhn(digits):
            card_count += 1
            return "[REDACTED:CREDIT_CARD]"
        return raw

    sanitized = _CARD_CANDIDATE_RE.sub(_replace_card, sanitized)
    if card_count > 0:
        findings.append(
            DLPFinding(
                category="CREDIT_CARD",
                redacted_token="[REDACTED:CREDIT_CARD]",
                count=card_count,
            )
        )

    has_pii = len(findings) > 0
    classification = (
        DataClassification.RESTRICTED_PII_OR_CREDENTIAL if has_pii else default_classification
    )
    return DLPScanResult(
        sanitized_text=sanitized,
        has_pii=has_pii,
        classification=classification,
        findings=findings,
    )


def classify_payload(source: str, *, has_pii: bool = False) -> str:
    """Return the data classification tag for a given data source or artifact."""
    if has_pii:
        return DataClassification.RESTRICTED_PII_OR_CREDENTIAL
    normalized = (source or "").strip().lower()
    if normalized in {"sec_edgar", "yahoo", "alpha_vantage", "finnhub", "offline_fixture", "market"}:
        return DataClassification.PUBLIC_MARKET_DATA
    if normalized in {"portfolio", "client_mandate"}:
        return DataClassification.CONFIDENTIAL_CLIENT_CONTEXT
    return DataClassification.INTERNAL_ANALYST_WORK_PRODUCT
