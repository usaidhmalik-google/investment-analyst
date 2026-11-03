"""Deterministic offline fixtures for demos, CI and golden-dataset evaluations.

Only used when ``ANALYST_OFFLINE_MODE=true``. Every payload is labelled with
``source="Offline Fixture"`` so it can never be mistaken for live market data.
"""

from __future__ import annotations

import random
import zlib
from datetime import date, timedelta

from .schemas import (
    FilingList,
    FilingRef,
    FilingSection,
    FinancialMetrics,
    NewsArticle,
    NewsFeed,
    PriceBar,
    PriceHistory,
    Quote,
    ReportedValue,
    XbrlFinancials,
)
from .yahoo import summarize_history

SOURCE = "Offline Fixture"
AS_OF = "2026-09-15T20:00:00+00:00"
END_DATE = date(2026, 9, 15)

_COMPANIES: dict[str, dict] = {
    "NVDA": {
        "name": "NVIDIA Corporation",
        "cik": "0001045810",
        "price": 128.50,
        "prev": 126.10,
        "market_cap": 3.15e12,
        "trailing_pe": 48.2,
        "forward_pe": 32.5,
        "hi52": 140.76,
        "lo52": 86.62,
        "volume": 48_500_000,
        "sector": "Technology",
        "industry": "Semiconductors",
        "dividend_rate": 0.04,
        "drift": 0.0016,
        "metrics": {
            "total_revenue": 60.92e9,
            "revenue_growth_pct": 122.4,
            "gross_margin_pct": 75.1,
            "operating_margin_pct": 61.5,
            "net_margin_pct": 53.4,
            "trailing_eps": 2.66,
            "forward_eps": 3.95,
            "return_on_equity_pct": 115.6,
            "debt_to_equity": 0.42,
            "free_cash_flow": 27.02e9,
            "price_to_book": 52.3,
            "peg_ratio": 1.12,
            "payout_ratio_pct": 1.5,
            "target_mean_price": 145.0,
            "analyst_consensus": "BUY",
            "number_of_analysts": 45,
        },
        "news": [
            ("Nvidia Blackwell Ultra production expands across hyperscale cloud providers", "Reuters", "2026-09-14"),
            ("Enterprise AI infrastructure spending forecast upgraded for fiscal 2027", "Bloomberg", "2026-09-12"),
            (
                "Blackwell energy-to-compute efficiency draws data center operator interest",
                "The Wall Street Journal",
                "2026-09-10",
            ),
        ],
    },
    "AAPL": {
        "name": "Apple Inc.",
        "cik": "0000320193",
        "price": 224.20,
        "prev": 225.05,
        "market_cap": 3.42e12,
        "trailing_pe": 33.8,
        "forward_pe": 28.4,
        "hi52": 237.23,
        "lo52": 164.08,
        "volume": 52_100_000,
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "dividend_rate": 1.00,
        "drift": 0.0006,
        "metrics": {
            "total_revenue": 385.6e9,
            "revenue_growth_pct": 4.9,
            "gross_margin_pct": 46.2,
            "operating_margin_pct": 31.2,
            "net_margin_pct": 25.3,
            "trailing_eps": 6.57,
            "forward_eps": 7.42,
            "return_on_equity_pct": 147.2,
            "debt_to_equity": 1.45,
            "free_cash_flow": 108.8e9,
            "price_to_book": 48.1,
            "peg_ratio": 2.9,
            "payout_ratio_pct": 15.2,
            "target_mean_price": 242.0,
            "analyst_consensus": "BUY",
            "number_of_analysts": 42,
        },
        "news": [
            ("Apple Intelligence features roll out globally with expanded language support", "Bloomberg", "2026-09-13"),
            ("Services revenue hits quarterly record on App Store and subscriptions", "Financial Times", "2026-09-11"),
        ],
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "cik": "0000789019",
        "price": 435.50,
        "prev": 431.20,
        "market_cap": 3.24e12,
        "trailing_pe": 35.6,
        "forward_pe": 29.8,
        "hi52": 468.35,
        "lo52": 309.45,
        "volume": 21_800_000,
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "dividend_rate": 3.32,
        "drift": 0.0008,
        "metrics": {
            "total_revenue": 245.12e9,
            "revenue_growth_pct": 15.2,
            "gross_margin_pct": 69.8,
            "operating_margin_pct": 44.6,
            "net_margin_pct": 36.1,
            "trailing_eps": 11.80,
            "forward_eps": 13.50,
            "return_on_equity_pct": 38.5,
            "debt_to_equity": 0.38,
            "free_cash_flow": 74.1e9,
            "price_to_book": 11.9,
            "peg_ratio": 2.2,
            "payout_ratio_pct": 25.4,
            "target_mean_price": 490.0,
            "analyst_consensus": "BUY",
            "number_of_analysts": 48,
        },
        "news": [
            ("Microsoft Cloud run-rate climbs on enterprise Copilot adoption", "Reuters", "2026-09-14"),
            (
                "Azure AI capacity expansions go live across Europe and North America",
                "The Wall Street Journal",
                "2026-09-11",
            ),
        ],
    },
    "KO": {
        "name": "The Coca-Cola Company",
        "cik": "0000021344",
        "price": 71.40,
        "prev": 71.15,
        "market_cap": 3.08e11,
        "trailing_pe": 23.1,
        "forward_pe": 21.6,
        "hi52": 73.53,
        "lo52": 57.93,
        "volume": 12_400_000,
        "sector": "Consumer Defensive",
        "industry": "Beverages - Non-Alcoholic",
        "dividend_rate": 2.04,
        "drift": 0.0003,
        "metrics": {
            "total_revenue": 46.4e9,
            "revenue_growth_pct": 3.1,
            "gross_margin_pct": 60.7,
            "operating_margin_pct": 29.8,
            "net_margin_pct": 23.0,
            "trailing_eps": 3.09,
            "forward_eps": 3.31,
            "return_on_equity_pct": 40.1,
            "debt_to_equity": 1.62,
            "free_cash_flow": 9.7e9,
            "price_to_book": 11.3,
            "peg_ratio": 3.4,
            "payout_ratio_pct": 66.0,
            "target_mean_price": 76.0,
            "analyst_consensus": "BUY",
            "number_of_analysts": 24,
        },
        "news": [
            ("Coca-Cola raises full-year organic revenue outlook on pricing", "Reuters", "2026-09-12"),
        ],
    },
}

_FILING_TEXT = (
    "Item 1A. Risk Factors\n\nOur operations are subject to competition, supply chain concentration, "
    "export controls, and macroeconomic conditions that could adversely affect demand for our products. "
    "Changes in customer capital expenditure cycles may cause revenue volatility. "
) * 8


def supported_tickers() -> list[str]:
    return sorted(_COMPANIES)


def _company(ticker: str) -> dict:
    symbol = ticker.upper()
    if symbol not in _COMPANIES:
        raise LookupError(f"No offline fixture for {symbol}. Offline tickers: {', '.join(supported_tickers())}")
    return _COMPANIES[symbol]


def quote(ticker: str) -> Quote:
    c = _company(ticker)
    change = round(c["price"] - c["prev"], 4)
    return Quote(
        ticker=ticker.upper(),
        company_name=c["name"],
        price=c["price"],
        previous_close=c["prev"],
        change=change,
        change_pct=round(change / c["prev"] * 100, 2),
        day_high=round(c["price"] * 1.01, 2),
        day_low=round(c["price"] * 0.985, 2),
        volume=c["volume"],
        average_volume=int(c["volume"] * 1.1),
        market_cap=c["market_cap"],
        trailing_pe=c["trailing_pe"],
        forward_pe=c["forward_pe"],
        fifty_two_week_high=c["hi52"],
        fifty_two_week_low=c["lo52"],
        dividend_yield_pct=round(c["dividend_rate"] / c["price"] * 100, 2),
        sector=c["sector"],
        industry=c["industry"],
        source=SOURCE,
        as_of=AS_OF,
    )


_PERIOD_DAYS = {"5d": 5, "1mo": 22, "3mo": 66, "6mo": 128, "1y": 252, "2y": 504, "5y": 1260, "ytd": 180}


def history(ticker: str, period: str) -> PriceHistory:
    """Deterministic synthetic daily bars ending at the fixture price (seeded per ticker)."""
    c = _company(ticker)
    n = _PERIOD_DAYS.get(period, 22)
    rng = random.Random(zlib.crc32(ticker.upper().encode()))  # noqa: S311 - deterministic fixtures
    total = 1300
    closes = [c["price"]]
    for _ in range(total - 1):
        shock = rng.gauss(c["drift"], 0.017)
        closes.append(round(closes[-1] / (1 + shock), 2))
    closes.reverse()
    closes = closes[-n:]
    bars: list[PriceBar] = []
    day = END_DATE
    dates: list[date] = []
    while len(dates) < n:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)
    dates.reverse()
    for d, close in zip(dates, closes, strict=True):
        spread = close * 0.012
        bars.append(
            PriceBar(
                date=d.isoformat(),
                open=round(close - spread / 3, 2),
                high=round(close + spread, 2),
                low=round(close - spread, 2),
                close=close,
                volume=int(c["volume"] * (0.8 + rng.random() * 0.4)),
            )
        )
    result = summarize_history(ticker.upper(), period, bars, SOURCE)
    result.as_of = AS_OF
    return result


def metrics(ticker: str) -> FinancialMetrics:
    c = _company(ticker)
    return FinancialMetrics(
        ticker=ticker.upper(), dividend_rate=c["dividend_rate"], source=SOURCE, as_of=AS_OF, **c["metrics"]
    )


def news(ticker: str, limit: int) -> NewsFeed:
    c = _company(ticker)
    articles = [NewsArticle(title=t, publisher=p, published=d, url=None, summary=None) for t, p, d in c["news"][:limit]]
    return NewsFeed(ticker=ticker.upper(), articles=articles, source=SOURCE, as_of=AS_OF)


def dividends(ticker: str) -> list[tuple[str, float]]:
    c = _company(ticker)
    if c["dividend_rate"] <= 0:
        return []
    out = []
    for years_ago in range(6, -1, -1):
        annual = c["dividend_rate"] / (1.05**years_ago)
        for q in range(4):
            out.append((f"{END_DATE.year - years_ago}-{3 * q + 2:02d}-15", round(annual / 4, 4)))
    return out


def filings(ticker: str, forms: tuple[str, ...], limit: int) -> FilingList:
    c = _company(ticker)
    refs = [
        FilingRef(
            form=form,
            filing_date="2026-08-27" if form != "10-K" else "2026-02-21",
            report_date=None,
            accession_number=f"{c['cik'][-7:]}-26-00000{i + 1}",
            primary_document=f"{ticker.lower()}-{form.lower()}.htm",
            url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={c['cik']}",
            description=f"{form} (offline fixture)",
        )
        for i, form in enumerate(forms[:limit])
    ]
    return FilingList(
        ticker=ticker.upper(), cik=c["cik"], company_name=c["name"], filings=refs, source=SOURCE, as_of=AS_OF
    )


def section(ticker: str, form: str, section_name: str, max_chars: int) -> FilingSection:
    listing = filings(ticker, (form.upper(),), 1)
    ref = listing.filings[0]
    return FilingSection(
        ticker=ticker.upper(),
        form=ref.form,
        accession_number=ref.accession_number,
        filing_date=ref.filing_date,
        section=section_name,
        section_title="Item 1A. Risk Factors",
        section_found=True,
        text=_FILING_TEXT[:max_chars],
        truncated=len(_FILING_TEXT) > max_chars,
        total_characters=len(_FILING_TEXT),
        url=ref.url,
        source=SOURCE,
        as_of=AS_OF,
    )


def xbrl(ticker: str) -> XbrlFinancials:
    c = _company(ticker)
    m = c["metrics"]
    rv = lambda concept, value, unit="USD": ReportedValue(  # noqa: E731
        concept=concept,
        value=value,
        unit=unit,
        period_end="2026-01-31",
        fiscal_year=2026,
        fiscal_period="FY",
        form="10-K",
    )
    return XbrlFinancials(
        ticker=ticker.upper(),
        cik=c["cik"],
        company_name=c["name"],
        annual={
            "revenue": rv("Revenues", m["total_revenue"]),
            "net_income": rv("NetIncomeLoss", round(m["total_revenue"] * m["net_margin_pct"] / 100, 0)),
            "eps_diluted": rv("EarningsPerShareDiluted", m["trailing_eps"], "USD/shares"),
        },
        source=SOURCE,
        as_of=AS_OF,
    )
