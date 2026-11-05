"""SEC Filing Parser tools: EDGAR filing index, section extraction and XBRL financials."""

from __future__ import annotations

from typing import Any

from google.adk.tools.tool_context import ToolContext

from ..data import market, rag
from .evidence import dump, record_evidence, safe_tool

ALLOWED_FORMS = ("10-K", "10-Q", "8-K", "DEF 14A", "4", "13F-HR")
SECTION_CHOICES = ("risk_factors", "mdna", "business", "legal_proceedings", "market_risk", "financial_statements")


@safe_tool
def list_sec_filings(
    ticker: str, form_types: list[str] | None = None, limit: int = 5, tool_context: ToolContext | None = None
) -> dict[str, Any]:
    """List a company's most recent SEC EDGAR filings.

    Args:
        ticker: Stock ticker symbol.
        form_types: Forms to include, any of "10-K", "10-Q", "8-K", "DEF 14A", "4", "13F-HR".
            Defaults to ["10-K", "10-Q", "8-K"].
        limit: Maximum number of filings to return (1-20).

    Returns:
        Filing references; each has a ``citation_id`` like ``[SEC:TICKER:10-K:ACCESSION]``.
    """
    forms = tuple(f.upper() for f in (form_types or ["10-K", "10-Q", "8-K"]))
    bad = [f for f in forms if f not in ALLOWED_FORMS]
    if bad:
        raise ValueError(f"Unsupported form types {bad}; allowed: {ALLOWED_FORMS}")
    listing = market.list_filings(ticker, forms, max(1, min(int(limit), 20)))
    filings = [
        record_evidence(
            tool_context,
            citation_id=f"SEC:{listing.ticker}:{f.form}:{f.accession_number}",
            type="sec_filing",
            title=f"{listing.company_name} {f.form} filed {f.filing_date}",
            source=listing.source,
            url=f.url,
            as_of=f.filing_date,
            data=dump(f),
        )
        for f in listing.filings
    ]
    return {"ticker": listing.ticker, "cik": listing.cik, "company_name": listing.company_name, "filings": filings}


@safe_tool
def get_sec_filing_section(
    ticker: str,
    form_type: str = "10-K",
    section: str = "risk_factors",
    accession_number: str | None = None,
    max_chars: int = 6000,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Extract the text of a section from a company's latest (or a specific) 10-K, 10-Q or 8-K filing.

    Args:
        ticker: Stock ticker symbol.
        form_type: "10-K", "10-Q" or "8-K".
        section: One of "risk_factors", "mdna", "business", "legal_proceedings", "market_risk",
            "financial_statements". Ignored for 8-K (the whole current report is returned).
        accession_number: Optional accession number from ``list_sec_filings``; defaults to the latest filing.
        max_chars: Maximum characters of section text to return (1000-15000).

    Returns:
        Section text with a ``citation_id`` like ``[SEC:TICKER:10-K:ACCESSION]``.
    """
    form = form_type.upper()
    if form not in ("10-K", "10-Q", "8-K"):
        raise ValueError("form_type must be 10-K, 10-Q or 8-K")
    if section not in SECTION_CHOICES:
        raise ValueError(f"section must be one of {SECTION_CHOICES}")
    sec = market.get_filing_section(ticker, form, section, accession_number, max(1000, min(int(max_chars), 15000)))
    return record_evidence(
        tool_context,
        citation_id=f"SEC:{sec.ticker}:{sec.form}:{sec.accession_number}",
        type="sec_filing",
        title=f"{sec.ticker} {sec.form} ({sec.filing_date}) — {sec.section_title}",
        source=sec.source,
        url=sec.url,
        as_of=sec.filing_date,
        data=dump(sec),
    )


@safe_tool
def get_sec_reported_financials(ticker: str, tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Fetch audited figures reported to the SEC in XBRL (latest annual and quarterly).

    Includes revenue, gross profit, operating income, net income, diluted EPS, operating cash flow,
    total assets/liabilities, stockholders' equity and cash.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Reported values with period, form and accession metadata; cite as ``[XBRL:TICKER]``.
    """
    x = market.get_xbrl_financials(ticker)
    return record_evidence(
        tool_context,
        citation_id=f"XBRL:{x.ticker}",
        type="sec_financials",
        title=f"{x.company_name} SEC XBRL reported financials",
        source=x.source,
        url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={x.cik}",
        as_of=x.as_of,
        data=dump(x),
    )


@safe_tool
def search_sec_filing(
    ticker: str,
    query: str,
    form_type: str = "10-K",
    section: str = "risk_factors",
    top_k: int = 3,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Run hybrid BM25 + dense-vector Reciprocal Rank Fusion (RRF) search over an SEC filing section.

    Args:
        ticker: Stock ticker symbol.
        query: Search query (e.g., "supply chain Taiwan foundry concentration" or "gross margin drivers").
        form_type: "10-K", "10-Q" or "8-K".
        section: Section to index and search ("risk_factors", "mdna", "business", "legal_proceedings",
            "market_risk", "financial_statements").
        top_k: Number of top-ranked chunks to return (1-10).
        chunk_size: Target character size per chunk (default 800).
        chunk_overlap: Character overlap between adjacent chunks (default 150).

    Returns:
        Top-ranked grounded chunks with BM25, dense cosine, and RRF scores, recorded under
        citation ``[SEC:TICKER:FORM:ACCESSION]``.
    """
    form = form_type.upper()
    if form not in ("10-K", "10-Q", "8-K"):
        raise ValueError("form_type must be 10-K, 10-Q or 8-K")
    if section not in SECTION_CHOICES:
        raise ValueError(f"section must be one of {SECTION_CHOICES}")
    clean_query = (query or "").strip()
    if not clean_query:
        raise ValueError("query must not be empty")

    sec = market.get_filing_section(ticker, form, section, None, 120000)
    chunks = rag.chunk_filing_section(
        sec.text,
        ticker=sec.ticker,
        form=sec.form,
        section=sec.section,
        accession_number=sec.accession_number,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    retriever = rag.HybridFilingRetriever(chunks)
    hits = retriever.search(clean_query, top_k=max(1, min(int(top_k), 10)))
    matched_chunks = [
        {
            "chunk_id": h.chunk.chunk_id,
            "chunk_index": h.chunk.chunk_index,
            "start_char": h.chunk.start_char,
            "end_char": h.chunk.end_char,
            "rrf_score": h.rrf_score,
            "bm25_score": h.bm25_score,
            "dense_score": h.dense_score,
            "text": h.chunk.text,
        }
        for h in hits
    ]
    payload = {
        "ticker": sec.ticker,
        "form": sec.form,
        "accession_number": sec.accession_number,
        "filing_date": sec.filing_date,
        "section": sec.section,
        "section_title": sec.section_title,
        "query": clean_query,
        "total_chunks": len(chunks),
        "matches": matched_chunks,
        "url": sec.url,
    }
    return record_evidence(
        tool_context,
        citation_id=f"SEC:{sec.ticker}:{sec.form}:{sec.accession_number}",
        type="sec_filing",
        title=f"{sec.ticker} {sec.form} ({sec.filing_date}) — {sec.section_title} [RAG: {clean_query}]",
        source=sec.source,
        url=sec.url,
        as_of=sec.filing_date,
        data=payload,
    )


SEC_FILING_TOOLS = [list_sec_filings, get_sec_filing_section, get_sec_reported_financials, search_sec_filing]
