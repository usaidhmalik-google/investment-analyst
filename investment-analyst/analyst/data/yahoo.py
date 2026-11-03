"""Yahoo Finance adapter (via ``yfinance``). Primary market-data provider."""

from __future__ import annotations

import contextlib
import math
from datetime import UTC, datetime
from typing import Any

from .schemas import FinancialMetrics, NewsArticle, NewsFeed, PriceBar, PriceHistory, Quote

SOURCE = "Yahoo Finance"
RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def num(value: Any, digits: int | None = 4) -> float | None:
    """Coerce provider values to float, mapping None/NaN/inf/garbage to ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits) if digits is not None else f


def pct(fraction: Any) -> float | None:
    """Convert a fractional ratio (0.1234) to percent units (12.34)."""
    f = num(fraction, None)
    return None if f is None else round(f * 100, 2)


def integer(value: Any) -> int | None:
    f = num(value, None)
    return None if f is None else int(f)


def _ticker(symbol: str):  # pragma: no cover - thin wrapper, patched in tests
    import yfinance as yf

    return yf.Ticker(symbol)


def fetch_quote(symbol: str) -> Quote:
    t = _ticker(symbol)
    info: dict[str, Any] = t.info or {}
    price = num(info.get("currentPrice")) or num(info.get("regularMarketPrice"))
    if price is None:
        price = num(getattr(t.fast_info, "last_price", None))
    if price is None:
        raise LookupError(f"Yahoo Finance returned no price for {symbol}")
    prev = num(info.get("previousClose")) or num(info.get("regularMarketPreviousClose"))
    change = round(price - prev, 4) if prev else None
    change_pct = round((price - prev) / prev * 100, 2) if prev else None
    dividend_rate = num(info.get("dividendRate")) or num(info.get("trailingAnnualDividendRate"))
    return Quote(
        ticker=symbol,
        company_name=info.get("longName") or info.get("shortName") or symbol,
        price=price,
        currency=info.get("currency") or "USD",
        previous_close=prev,
        change=change,
        change_pct=change_pct,
        day_high=num(info.get("dayHigh")),
        day_low=num(info.get("dayLow")),
        volume=integer(info.get("regularMarketVolume") or info.get("volume")),
        average_volume=integer(info.get("averageVolume")),
        market_cap=num(info.get("marketCap"), 0),
        trailing_pe=num(info.get("trailingPE"), 2),
        forward_pe=num(info.get("forwardPE"), 2),
        fifty_two_week_high=num(info.get("fiftyTwoWeekHigh")),
        fifty_two_week_low=num(info.get("fiftyTwoWeekLow")),
        dividend_yield_pct=round(dividend_rate / price * 100, 2) if dividend_rate else None,
        sector=info.get("sector"),
        industry=info.get("industry"),
        source=SOURCE,
        as_of=now_iso(),
    )


def fetch_history(symbol: str, period: str) -> PriceHistory:
    t = _ticker(symbol)
    frame = t.history(period=period, interval="1d", auto_adjust=False)
    if frame is None or frame.empty:
        raise LookupError(f"Yahoo Finance returned no price history for {symbol}")
    bars: list[PriceBar] = []
    for idx, row in frame.iterrows():
        close = num(row.get("Close"))
        if close is None:
            continue
        bars.append(
            PriceBar(
                date=idx.strftime("%Y-%m-%d"),
                open=num(row.get("Open")) or close,
                high=num(row.get("High")) or close,
                low=num(row.get("Low")) or close,
                close=close,
                volume=integer(row.get("Volume")) or 0,
            )
        )
    return summarize_history(symbol, period, bars, SOURCE)


def summarize_history(symbol: str, period: str, bars: list[PriceBar], source: str) -> PriceHistory:
    if not bars:
        raise LookupError(f"No price bars for {symbol}")
    first, last = bars[0], bars[-1]
    change = round(last.close - first.close, 4)
    return PriceHistory(
        ticker=symbol,
        period=period,
        start_date=first.date,
        end_date=last.date,
        start_close=first.close,
        end_close=last.close,
        change=change,
        change_pct=round(change / first.close * 100, 2) if first.close else 0.0,
        period_high=max(b.high for b in bars),
        period_low=min(b.low for b in bars),
        average_volume=int(sum(b.volume for b in bars) / len(bars)),
        bars=bars,
        source=source,
        as_of=now_iso(),
    )


def fetch_metrics(symbol: str) -> FinancialMetrics:
    info: dict[str, Any] = _ticker(symbol).info or {}
    if not info or ("totalRevenue" not in info and "trailingEps" not in info):
        raise LookupError(f"Yahoo Finance returned no fundamentals for {symbol}")
    dte = num(info.get("debtToEquity"), None)
    recommendation = info.get("recommendationKey")
    return FinancialMetrics(
        ticker=symbol,
        total_revenue=num(info.get("totalRevenue"), 0),
        revenue_growth_pct=pct(info.get("revenueGrowth")),
        gross_margin_pct=pct(info.get("grossMargins")),
        operating_margin_pct=pct(info.get("operatingMargins")),
        net_margin_pct=pct(info.get("profitMargins")),
        trailing_eps=num(info.get("trailingEps"), 2),
        forward_eps=num(info.get("forwardEps"), 2),
        return_on_equity_pct=pct(info.get("returnOnEquity")),
        # Yahoo reports debt/equity in percent (e.g. 41.2 == 0.412x); normalise to a ratio.
        debt_to_equity=round(dte / 100, 2) if dte is not None else None,
        free_cash_flow=num(info.get("freeCashflow"), 0),
        price_to_book=num(info.get("priceToBook"), 2),
        peg_ratio=num(info.get("trailingPegRatio") or info.get("pegRatio"), 2),
        dividend_rate=num(info.get("dividendRate"), 2),
        payout_ratio_pct=pct(info.get("payoutRatio")),
        target_mean_price=num(info.get("targetMeanPrice"), 2),
        analyst_consensus=recommendation.upper() if isinstance(recommendation, str) else None,
        number_of_analysts=integer(info.get("numberOfAnalystOpinions")),
        source=SOURCE,
        as_of=now_iso(),
    )


def fetch_news(symbol: str, limit: int) -> NewsFeed:
    raw = _ticker(symbol).news or []
    articles: list[NewsArticle] = []
    for item in raw[:limit]:
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
        url = None
        for key in ("canonicalUrl", "clickThroughUrl"):
            if isinstance(content.get(key), dict) and content[key].get("url"):
                url = content[key]["url"]
                break
        url = url or item.get("link")
        published = content.get("pubDate") or item.get("providerPublishTime")
        if isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published, UTC).isoformat(timespec="seconds")
        title = content.get("title") or item.get("title")
        if not title:
            continue
        articles.append(
            NewsArticle(
                title=title,
                publisher=provider.get("displayName") or item.get("publisher"),
                published=published,
                url=url,
                summary=(content.get("summary") or content.get("description") or None),
            )
        )
    if not articles:
        raise LookupError(f"Yahoo Finance returned no news for {symbol}")
    return NewsFeed(ticker=symbol, articles=articles, source=SOURCE, as_of=now_iso())


def fetch_news_rss(symbol: str, limit: int) -> NewsFeed:
    """Fallback: Yahoo Finance headline RSS feed (used when the JSON news endpoint is empty)."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    from . import http

    response = http.get(
        RSS_URL,
        operation="yahoo.news_rss",
        params={"s": symbol, "region": "US", "lang": "en-US"},
        headers={"User-Agent": "Mozilla/5.0 (compatible; MALIK-Investment-Analyst/1.0)"},
    )
    root = ET.fromstring(response.text)  # noqa: S314
    articles: list[NewsArticle] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        published = item.findtext("pubDate")
        if published:
            with contextlib.suppress(TypeError, ValueError):
                published = parsedate_to_datetime(published).astimezone(UTC).isoformat(timespec="seconds")
        articles.append(
            NewsArticle(
                title=title,
                publisher="Yahoo Finance",
                published=published,
                url=(item.findtext("link") or "").strip() or None,
                summary=(item.findtext("description") or "").strip() or None,
            )
        )
        if len(articles) >= limit:
            break
    if not articles:
        raise LookupError(f"Yahoo Finance RSS returned no news for {symbol}")
    return NewsFeed(ticker=symbol, articles=articles, source=SOURCE, as_of=now_iso())


def fetch_dividends(symbol: str) -> list[tuple[str, float]]:
    """Return ``[(YYYY-MM-DD, amount), ...]`` dividend history (may be empty)."""
    series = _ticker(symbol).dividends
    if series is None or len(series) == 0:
        return []
    return [(idx.strftime("%Y-%m-%d"), float(val)) for idx, val in series.items()]
