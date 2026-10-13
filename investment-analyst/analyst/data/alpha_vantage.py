"""Alpha Vantage adapter — secondary provider used when Yahoo Finance fails or rate-limits."""

from __future__ import annotations

from typing import Any

from ..tools.resilience import DataProviderError, RateLimitedError, call_with_retry
from . import http
from .schemas import FinancialMetrics, NewsArticle, NewsFeed, PriceBar, PriceHistory, Quote
from .secrets import get_alpha_vantage_key
from .yahoo import integer, now_iso, num, pct, summarize_history

BASE_URL = "https://www.alphavantage.co/query"
SOURCE = "Alpha Vantage"

_PERIOD_TO_BARS = {"5d": 5, "1mo": 22, "3mo": 66, "6mo": 128, "1y": 252, "2y": 504, "5y": 1260}


def is_configured() -> bool:
    return bool(get_alpha_vantage_key())


def _query(function: str, **params: Any) -> dict[str, Any]:
    key = get_alpha_vantage_key()
    if not key:
        raise DataProviderError("Alpha Vantage API key not configured")

    def _attempt() -> dict[str, Any]:
        response = http.get_once(BASE_URL, params={"function": function, "apikey": key, **params})
        payload = response.json()
        # Alpha Vantage signals throttling with HTTP 200 + a "Note"/"Information" body.
        if "Note" in payload or ("Information" in payload and len(payload) == 1):
            raise RateLimitedError(str(payload.get("Note") or payload.get("Information")), retry_after=None)
        if "Error Message" in payload:
            raise DataProviderError(payload["Error Message"])
        return payload

    return call_with_retry(_attempt, policy=http.retry_policy(), operation=f"alphavantage.{function}")


def fetch_quote(symbol: str) -> Quote:
    data = _query("GLOBAL_QUOTE", symbol=symbol).get("Global Quote") or {}
    price = num(data.get("05. price"))
    if price is None:
        raise LookupError(f"Alpha Vantage returned no quote for {symbol}")
    change_pct_raw = str(data.get("10. change percent", "")).rstrip("%")
    return Quote(
        ticker=symbol,
        company_name=symbol,
        price=price,
        previous_close=num(data.get("08. previous close")),
        change=num(data.get("09. change")),
        change_pct=num(change_pct_raw, 2),
        day_high=num(data.get("03. high")),
        day_low=num(data.get("04. low")),
        volume=integer(data.get("06. volume")),
        source=SOURCE,
        as_of=data.get("07. latest trading day") or now_iso(),
    )


def fetch_history(symbol: str, period: str) -> PriceHistory:
    bars_needed = _PERIOD_TO_BARS.get(period, 22)
    output_size = "compact" if bars_needed <= 100 else "full"
    series = _query("TIME_SERIES_DAILY", symbol=symbol, outputsize=output_size).get("Time Series (Daily)") or {}
    if not series:
        raise LookupError(f"Alpha Vantage returned no history for {symbol}")
    dates = sorted(series.keys())[-bars_needed:]
    bars = [
        PriceBar(
            date=d,
            open=float(series[d]["1. open"]),
            high=float(series[d]["2. high"]),
            low=float(series[d]["3. low"]),
            close=float(series[d]["4. close"]),
            volume=int(float(series[d]["5. volume"])),
        )
        for d in dates
    ]
    return summarize_history(symbol, period, bars, SOURCE)


def fetch_metrics(symbol: str) -> FinancialMetrics:
    data = _query("OVERVIEW", symbol=symbol)
    if not data or "Symbol" not in data:
        raise LookupError(f"Alpha Vantage returned no overview for {symbol}")
    return FinancialMetrics(
        ticker=symbol,
        total_revenue=num(data.get("RevenueTTM"), 0),
        revenue_growth_pct=pct(data.get("QuarterlyRevenueGrowthYOY")),
        gross_margin_pct=None,
        operating_margin_pct=pct(data.get("OperatingMarginTTM")),
        net_margin_pct=pct(data.get("ProfitMargin")),
        trailing_eps=num(data.get("EPS"), 2),
        forward_eps=None,
        return_on_equity_pct=pct(data.get("ReturnOnEquityTTM")),
        price_to_book=num(data.get("PriceToBookRatio"), 2),
        peg_ratio=num(data.get("PEGRatio"), 2),
        dividend_rate=num(data.get("DividendPerShare"), 2),
        target_mean_price=num(data.get("AnalystTargetPrice"), 2),
        source=SOURCE,
        as_of=now_iso(),
    )


def fetch_news(symbol: str, limit: int) -> NewsFeed:
    feed = _query("NEWS_SENTIMENT", tickers=symbol, limit=limit).get("feed") or []
    articles = [
        NewsArticle(
            title=item.get("title", ""),
            publisher=item.get("source"),
            published=item.get("time_published"),
            url=item.get("url"),
            summary=item.get("summary"),
        )
        for item in feed[:limit]
        if item.get("title")
    ]
    if not articles:
        raise LookupError(f"Alpha Vantage returned no news for {symbol}")
    return NewsFeed(ticker=symbol, articles=articles, source=SOURCE, as_of=now_iso())
