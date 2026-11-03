"""Data Gatherer tools: real-time quotes, price history, fundamentals and news."""

from __future__ import annotations

from typing import Any

from google.adk.tools.tool_context import ToolContext

from ..data import market
from .evidence import dump, record_evidence, safe_tool

MAX_BARS_TO_MODEL = 10


@safe_tool
def get_stock_quote(ticker: str, tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Fetch the real-time quote for a stock: price, daily change, volume, market cap, P/E and 52-week range.

    Args:
        ticker: Stock ticker symbol, e.g. "NVDA", "AAPL", "GOOGL".

    Returns:
        The quote payload with a ``citation_id`` you must cite as ``[Q:TICKER]``.
    """
    q = market.get_quote(ticker)
    return record_evidence(
        tool_context,
        citation_id=f"Q:{q.ticker}",
        type="quote",
        title=f"{q.company_name} real-time quote",
        source=q.source,
        url=f"https://finance.yahoo.com/quote/{q.ticker}" if q.source == "Yahoo Finance" else None,
        as_of=q.as_of,
        data=dump(q),
    )


@safe_tool
def get_price_history(ticker: str, period: str = "5d", tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Fetch daily price history and performance statistics for a time window.

    Use "5d" for "this week", "1mo" for "this month", "3mo"/"6mo"/"ytd"/"1y"/"2y"/"5y" for longer trends.

    Args:
        ticker: Stock ticker symbol.
        period: One of "5d", "1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y".

    Returns:
        Start/end close, absolute and percent change, period high/low, average volume and the most
        recent daily bars, with a ``citation_id`` like ``[H:TICKER:5d]``.
    """
    h = market.get_history(ticker, period)
    payload = dump(h, exclude={"bars"})
    payload["recent_bars"] = [b.model_dump() for b in h.bars[-MAX_BARS_TO_MODEL:]]
    return record_evidence(
        tool_context,
        citation_id=f"H:{h.ticker}:{h.period}",
        type="history",
        title=f"{h.ticker} price history ({h.start_date} to {h.end_date})",
        source=h.source,
        url=f"https://finance.yahoo.com/quote/{h.ticker}/history" if h.source == "Yahoo Finance" else None,
        as_of=h.as_of,
        data=payload,
    )


@safe_tool
def get_financial_metrics(ticker: str, tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Fetch fundamentals: revenue, growth, margins, EPS, ROE, leverage, free cash flow and analyst targets.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Fundamentals payload with a ``citation_id`` you must cite as ``[M:TICKER]``.
    """
    m = market.get_metrics(ticker)
    return record_evidence(
        tool_context,
        citation_id=f"M:{m.ticker}",
        type="metrics",
        title=f"{m.ticker} fundamentals and analyst consensus",
        source=m.source,
        url=f"https://finance.yahoo.com/quote/{m.ticker}/key-statistics" if m.source == "Yahoo Finance" else None,
        as_of=m.as_of,
        data=dump(m),
    )


@safe_tool
def get_company_news(ticker: str, limit: int = 5, tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Fetch the latest news articles about a company.

    Args:
        ticker: Stock ticker symbol.
        limit: Number of articles to return (1-10).

    Returns:
        A list of articles; each has its own ``citation_id`` like ``[N:TICKER:1]``.
    """
    feed = market.get_news(ticker, limit)
    articles = []
    for i, article in enumerate(feed.articles, start=1):
        articles.append(
            record_evidence(
                tool_context,
                citation_id=f"N:{feed.ticker}:{i}",
                type="news",
                title=article.title,
                source=article.publisher or feed.source,
                url=article.url,
                as_of=article.published or feed.as_of,
                data=dump(article),
            )
        )
    return {"ticker": feed.ticker, "source": feed.source, "articles": articles}


DATA_GATHERER_TOOLS = [get_stock_quote, get_price_history, get_financial_metrics, get_company_news]
