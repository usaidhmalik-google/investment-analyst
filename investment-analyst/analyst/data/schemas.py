"""Pydantic schemas for every deterministic data payload the agents can see.

All numeric fields are raw numbers (never pre-formatted strings) so that the
post-generation fact checker can verify every figure in the narrative against
the exact API output. Percentages are expressed in percent units (``12.5`` == 12.5%).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvidenceType = Literal["quote", "history", "metrics", "news", "sec_filing", "sec_financials", "strategy"]


class Citation(BaseModel):
    """A single citable source shown to the analyst next to the narrative."""

    id: str
    type: EvidenceType
    title: str
    source: str
    url: str | None = None
    as_of: str | None = None


class Quote(BaseModel):
    ticker: str
    company_name: str
    price: float
    currency: str = "USD"
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    average_volume: int | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    dividend_yield_pct: float | None = None
    sector: str | None = None
    industry: str | None = None
    source: str
    as_of: str


class PriceBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class PriceHistory(BaseModel):
    ticker: str
    period: str
    interval: str = "1d"
    start_date: str
    end_date: str
    start_close: float
    end_close: float
    change: float
    change_pct: float
    period_high: float
    period_low: float
    average_volume: int
    bars: list[PriceBar] = Field(default_factory=list)
    source: str
    as_of: str


class FinancialMetrics(BaseModel):
    ticker: str
    total_revenue: float | None = None
    revenue_growth_pct: float | None = None
    gross_margin_pct: float | None = None
    operating_margin_pct: float | None = None
    net_margin_pct: float | None = None
    trailing_eps: float | None = None
    forward_eps: float | None = None
    return_on_equity_pct: float | None = None
    debt_to_equity: float | None = None
    free_cash_flow: float | None = None
    price_to_book: float | None = None
    peg_ratio: float | None = None
    dividend_rate: float | None = None
    payout_ratio_pct: float | None = None
    target_mean_price: float | None = None
    analyst_consensus: str | None = None
    number_of_analysts: int | None = None
    source: str
    as_of: str


class NewsArticle(BaseModel):
    title: str
    publisher: str | None = None
    published: str | None = None
    url: str | None = None
    summary: str | None = None


class NewsFeed(BaseModel):
    ticker: str
    articles: list[NewsArticle]
    source: str
    as_of: str


class FilingRef(BaseModel):
    form: str
    filing_date: str
    report_date: str | None = None
    accession_number: str
    primary_document: str
    url: str
    description: str | None = None


class FilingList(BaseModel):
    ticker: str
    cik: str
    company_name: str
    filings: list[FilingRef]
    source: str = "SEC EDGAR"
    as_of: str


class FilingSection(BaseModel):
    ticker: str
    form: str
    accession_number: str
    filing_date: str
    section: str
    section_title: str
    section_found: bool
    text: str
    truncated: bool
    total_characters: int
    url: str
    items_detected: list[str] = Field(default_factory=list)
    source: str = "SEC EDGAR"
    as_of: str


class ReportedValue(BaseModel):
    concept: str
    value: float
    unit: str
    period_end: str
    period_start: str | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str | None = None
    filed: str | None = None
    accession_number: str | None = None


class XbrlFinancials(BaseModel):
    ticker: str
    cik: str
    company_name: str
    annual: dict[str, ReportedValue] = Field(default_factory=dict)
    quarterly: dict[str, ReportedValue] = Field(default_factory=dict)
    source: str = "SEC EDGAR XBRL"
    as_of: str


class StrategySignal(BaseModel):
    ticker: str
    strategy: Literal["momentum", "value", "swing", "income"]
    signal: str
    score: float
    max_score: float
    indicators: dict[str, float | str | bool | None]
    rationale: list[str]
    source: str = "Strategy Engine"
    as_of: str
