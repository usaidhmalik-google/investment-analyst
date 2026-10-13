"""SEC EDGAR adapter: ticker→CIK lookup, filing index, section extraction and XBRL facts.

Complies with the SEC fair-access policy: declared User-Agent and <= 10 requests/second.
Parsing never raises on unexpected document layouts — it degrades to returning the
beginning of the document with ``section_found=False`` (zero parsing failures).
"""

from __future__ import annotations

import html
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any

from ..config import get_settings
from ..tools.resilience import cached
from . import http
from .schemas import FilingList, FilingRef, FilingSection, ReportedValue, XbrlFinancials
from .yahoo import now_iso

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{document}"

SUPPORTED_FORMS = ("10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "8-K/A", "DEF 14A", "4", "13F-HR")

_limiter = http.MinIntervalLimiter(0.11)


def _headers() -> dict[str, str]:
    return {"User-Agent": get_settings().sec_user_agent}


def _sec_ttl() -> float:
    return get_settings().sec_cache_ttl_seconds


def _get_json(url: str, operation: str) -> Any:
    return http.get(url, operation=operation, headers=_headers(), limiter=_limiter).json()


@cached(_sec_ttl, maxsize=1)
def _ticker_map() -> dict[str, tuple[str, str]]:
    raw = _get_json(TICKER_MAP_URL, "sec.ticker_map")
    rows = raw.values() if isinstance(raw, dict) else raw
    return {str(row["ticker"]).upper(): (str(row["cik_str"]).zfill(10), str(row.get("title", ""))) for row in rows}


def resolve_cik(ticker: str) -> tuple[str, str]:
    """Return ``(10-digit CIK, company name)`` for a ticker. Raises ``LookupError`` if unknown."""
    symbol = ticker.upper().replace(".", "-")
    mapping = _ticker_map()
    if symbol not in mapping:
        raise LookupError(f"Ticker {ticker} not found in SEC EDGAR company list")
    return mapping[symbol]


@cached(_sec_ttl, maxsize=256)
def _submissions(cik: str) -> dict[str, Any]:
    return _get_json(SUBMISSIONS_URL.format(cik=cik), "sec.submissions")


def list_filings(ticker: str, forms: tuple[str, ...], limit: int) -> FilingList:
    cik, name = resolve_cik(ticker)
    data = _submissions(cik)
    recent = (data.get("filings") or {}).get("recent") or {}
    wanted = {f.upper() for f in forms}
    filings: list[FilingRef] = []
    for i, form in enumerate(recent.get("form", [])):
        if form.upper() not in wanted:
            continue
        accession = recent["accessionNumber"][i]
        document = recent["primaryDocument"][i]
        filings.append(
            FilingRef(
                form=form,
                filing_date=recent["filingDate"][i],
                report_date=(recent.get("reportDate") or [None] * (i + 1))[i] or None,
                accession_number=accession,
                primary_document=document,
                url=ARCHIVE_URL.format(
                    cik_int=int(cik), accession_nodash=accession.replace("-", ""), document=document
                ),
                description=(recent.get("primaryDocDescription") or [None] * (i + 1))[i] or None,
            )
        )
        if len(filings) >= limit:
            break
    return FilingList(
        ticker=ticker.upper(), cik=cik, company_name=data.get("name") or name, filings=filings, as_of=now_iso()
    )


# --------------------------------------------------------------------------- HTML → text


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = frozenset({"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"})
    _SKIP_TAGS = frozenset({"script", "style", "head", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip += 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")
        # Inline XBRL hidden header blocks contain machine-only facts.
        if tag == "ix:header":
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS or tag == "ix:header":
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(document: str) -> str:
    """Convert an EDGAR HTML/iXBRL (or plain-text) filing to normalised plain text."""
    if "<" not in document[:5000]:
        text = document
    else:
        parser = _TextExtractor()
        try:
            parser.feed(document)
            parser.close()
            text = "".join(parser.parts)
        except Exception:  # noqa: BLE001 - malformed markup: strip tags crudely
            text = re.sub(r"<[^>]+>", " ", document)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- section extraction

# Each section: (title, start-heading regex, form family)
SECTIONS: dict[str, dict[str, tuple[str, str]]] = {
    "10-K": {
        "business": ("Item 1. Business", r"item\s*1\.?\s*[\-–—:]?\s*business"),
        "risk_factors": ("Item 1A. Risk Factors", r"item\s*1a\.?\s*[\-–—:]?\s*risk\s+factors"),
        "legal_proceedings": ("Item 3. Legal Proceedings", r"item\s*3\.?\s*[\-–—:]?\s*legal\s+proceedings"),
        "mdna": (
            "Item 7. Management's Discussion and Analysis",
            r"item\s*7\.?\s*[\-–—:]?\s*management[’'`s]*\s+discussion",
        ),
        "market_risk": ("Item 7A. Market Risk", r"item\s*7a\.?\s*[\-–—:]?\s*quantitative\s+and\s+qualitative"),
        "financial_statements": ("Item 8. Financial Statements", r"item\s*8\.?\s*[\-–—:]?\s*financial\s+statements"),
    },
    "10-Q": {
        "financial_statements": (
            "Part I, Item 1. Financial Statements",
            r"item\s*1\.?\s*[\-–—:]?\s*financial\s+statements",
        ),
        "mdna": (
            "Part I, Item 2. Management's Discussion and Analysis",
            r"item\s*2\.?\s*[\-–—:]?\s*management[’'`s]*\s+discussion",
        ),
        "market_risk": ("Part I, Item 3. Market Risk", r"item\s*3\.?\s*[\-–—:]?\s*quantitative\s+and\s+qualitative"),
        "risk_factors": ("Part II, Item 1A. Risk Factors", r"item\s*1a\.?\s*[\-–—:]?\s*risk\s+factors"),
        "legal_proceedings": ("Part II, Item 1. Legal Proceedings", r"item\s*1\.?\s*[\-–—:]?\s*legal\s+proceedings"),
    },
}

_ANY_ITEM_HEADING = re.compile(
    r"\n\s*(?:part\s+[iv]+\s*[,\-–—]?\s*)?item\s*\d{1,2}[a-c]?\.?(?:\d{2})?\s*[\-–—:.]?\s*[a-z]", re.I
)
_8K_ITEM = re.compile(r"item\s*(\d\.\d{2})", re.I)


def extract_section(text: str, form: str, section: str) -> tuple[str, str, bool]:
    """Return ``(section_title, section_text, found)``.

    Picks the longest candidate span between the requested heading and the next
    ``Item N`` heading, which skips table-of-contents entries automatically.
    """
    family = "10-Q" if form.upper().startswith("10-Q") else "10-K"
    spec = SECTIONS[family].get(section)
    if spec is None:
        return section, text, False
    title, pattern = spec
    start_re = re.compile(pattern, re.I)
    best = ""
    for match in start_re.finditer(text):
        nxt = _ANY_ITEM_HEADING.search(text, match.end() + 200)
        end = nxt.start() if nxt else len(text)
        candidate = text[match.start() : end].strip()
        if len(candidate) > len(best):
            best = candidate
    if len(best) < 400:  # only a TOC hit or nothing at all
        return title, text, False
    return title, best, True


@cached(_sec_ttl, maxsize=64)
def _filing_text(url: str) -> str:
    response = http.get(url, operation="sec.filing_document", headers=_headers(), limiter=_limiter)
    return html_to_text(response.text)


def get_section(ticker: str, form: str, section: str, accession_number: str | None, max_chars: int) -> FilingSection:
    form = form.upper()
    listing = list_filings(ticker, (form,), limit=20)
    if not listing.filings:
        raise LookupError(f"No {form} filings found for {ticker}")
    filing = listing.filings[0]
    if accession_number:
        matches = [f for f in listing.filings if f.accession_number == accession_number]
        if matches:
            filing = matches[0]
    text = _filing_text(filing.url)
    if form.startswith("8-K"):
        items = sorted(set(_8K_ITEM.findall(text)))
        title, body, found = "Current Report (8-K)", text, True
    else:
        items = []
        title, body, found = extract_section(text, form, section)
    truncated = len(body) > max_chars
    return FilingSection(
        ticker=ticker.upper(),
        form=filing.form,
        accession_number=filing.accession_number,
        filing_date=filing.filing_date,
        section=section,
        section_title=title,
        section_found=found,
        text=body[:max_chars],
        truncated=truncated,
        total_characters=len(body),
        url=filing.url,
        items_detected=items,
        as_of=now_iso(),
    )


# --------------------------------------------------------------------------- XBRL facts

XBRL_CONCEPTS: dict[str, tuple[tuple[str, ...], str, bool]] = {
    # name: (candidate us-gaap concepts, unit, is_duration)
    "revenue": (
        ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
        "USD",
        True,
    ),
    "gross_profit": (("GrossProfit",), "USD", True),
    "operating_income": (("OperatingIncomeLoss",), "USD", True),
    "net_income": (("NetIncomeLoss",), "USD", True),
    "eps_diluted": (("EarningsPerShareDiluted",), "USD/shares", True),
    "operating_cash_flow": (("NetCashProvidedByUsedInOperatingActivities",), "USD", True),
    "total_assets": (("Assets",), "USD", False),
    "total_liabilities": (("Liabilities",), "USD", False),
    "stockholders_equity": (("StockholdersEquity",), "USD", False),
    "cash_and_equivalents": (("CashAndCashEquivalentsAtCarryingValue",), "USD", False),
}


def _duration_days(fact: dict[str, Any]) -> int | None:
    if not fact.get("start"):
        return None
    try:
        return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
    except ValueError:
        return None


def _pick_latest(facts: list[dict[str, Any]], annual: bool, is_duration: bool) -> dict[str, Any] | None:
    forms = ("10-K", "10-K/A") if annual else ("10-Q", "10-Q/A")
    candidates = []
    for fact in facts:
        if fact.get("form") not in forms:
            continue
        if is_duration:
            days = _duration_days(fact)
            if days is None:
                continue
            if annual and not 340 <= days <= 380:
                continue
            if not annual and not 80 <= days <= 100:
                continue
        candidates.append(fact)
    if not candidates:
        return None
    return max(candidates, key=lambda f: (f.get("end", ""), f.get("filed", "")))


@cached(_sec_ttl, maxsize=128)
def _company_facts(cik: str) -> dict[str, Any]:
    return _get_json(COMPANY_FACTS_URL.format(cik=cik), "sec.company_facts")


def get_xbrl_financials(ticker: str) -> XbrlFinancials:
    cik, name = resolve_cik(ticker)
    facts = _company_facts(cik)
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    result = XbrlFinancials(
        ticker=ticker.upper(), cik=cik, company_name=facts.get("entityName") or name, as_of=now_iso()
    )
    for key, (concepts, unit, is_duration) in XBRL_CONCEPTS.items():
        for annual, bucket in ((True, result.annual), (False, result.quarterly)):
            best: tuple[str, dict[str, Any]] | None = None
            for concept in concepts:
                unit_facts = ((gaap.get(concept) or {}).get("units") or {}).get(unit) or []
                fact = _pick_latest(unit_facts, annual, is_duration)
                if fact and (best is None or fact["end"] > best[1]["end"]):
                    best = (concept, fact)
            if best:
                concept, fact = best
                bucket[key] = ReportedValue(
                    concept=concept,
                    value=float(fact["val"]),
                    unit=unit,
                    period_end=fact["end"],
                    period_start=fact.get("start"),
                    fiscal_year=fact.get("fy"),
                    fiscal_period=fact.get("fp"),
                    form=fact.get("form"),
                    filed=fact.get("filed"),
                    accession_number=fact.get("accn"),
                )
    if not result.annual and not result.quarterly:
        raise LookupError(f"No standard us-gaap XBRL facts found for {ticker}")
    return result
