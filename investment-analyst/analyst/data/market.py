"""Provider facade: offline fixtures → Yahoo Finance → Alpha Vantage, with caching.

Every function returns a validated Pydantic model or raises ``DataProviderError``
after all providers are exhausted. Retries/backoff happen inside each adapter;
this layer handles cross-provider fallback (TDD: API Resiliency >= 99.9%).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from ..config import get_settings
from ..tools.resilience import DataProviderError, RetryPolicy, cached, call_with_retry
from . import alpha_vantage, fixtures, sec_edgar, yahoo
from .schemas import FilingList, FilingSection, FinancialMetrics, NewsFeed, PriceHistory, Quote, XbrlFinancials

logger = logging.getLogger(__name__)

T = TypeVar("T")

VALID_PERIODS = ("5d", "1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y")


def _policy() -> RetryPolicy:
    s = get_settings()
    return RetryPolicy(
        max_retries=s.http_max_retries, base_delay=s.http_backoff_base_seconds, max_delay=s.http_backoff_max_seconds
    )


def _chain(operation: str, providers: list[tuple[str, Callable[[], T]]]) -> T:
    errors: list[str] = []
    for name, fn in providers:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - try next provider
            logger.warning(
                "provider failed; falling back", extra={"provider": name, "operation": operation, "error": repr(exc)}
            )
            errors.append(f"{name}: {exc}")
    raise DataProviderError(f"All providers failed for {operation}: " + "; ".join(errors))


def _yahoo(operation: str, fn: Callable[[], T]) -> Callable[[], T]:
    """yfinance has no built-in backoff, so wrap it; Alpha Vantage/SEC adapters retry internally."""
    return lambda: call_with_retry(fn, policy=_policy(), operation=f"yahoo.{operation}")


def normalize_ticker(ticker: str) -> str:
    symbol = (ticker or "").strip().upper().lstrip("$")
    if not symbol or len(symbol) > 10 or not all(ch.isalnum() or ch in ".-^=" for ch in symbol):
        raise ValueError(f"Invalid ticker symbol: {ticker!r}")
    return symbol


def _quote_ttl() -> float:
    return get_settings().quote_cache_ttl_seconds


def _data_ttl() -> float:
    return get_settings().data_cache_ttl_seconds


def _offline() -> bool:
    return get_settings().offline_mode


@cached(_quote_ttl)
def get_quote(ticker: str) -> Quote:
    symbol = normalize_ticker(ticker)
    if _offline():
        return fixtures.quote(symbol)
    providers: list[tuple[str, Callable[[], Quote]]] = [("yahoo", _yahoo("quote", lambda: yahoo.fetch_quote(symbol)))]
    if alpha_vantage.is_configured():
        providers.append(("alpha_vantage", lambda: alpha_vantage.fetch_quote(symbol)))
    return _chain("quote", providers)


@cached(_data_ttl)
def get_history(ticker: str, period: str = "1mo") -> PriceHistory:
    symbol = normalize_ticker(ticker)
    if period not in VALID_PERIODS:
        raise ValueError(f"period must be one of {VALID_PERIODS}")
    if _offline():
        return fixtures.history(symbol, period)
    providers: list[tuple[str, Callable[[], PriceHistory]]] = [
        ("yahoo", _yahoo("history", lambda: yahoo.fetch_history(symbol, period)))
    ]
    if alpha_vantage.is_configured():
        providers.append(("alpha_vantage", lambda: alpha_vantage.fetch_history(symbol, period)))
    return _chain("history", providers)


@cached(_data_ttl)
def get_metrics(ticker: str) -> FinancialMetrics:
    symbol = normalize_ticker(ticker)
    if _offline():
        return fixtures.metrics(symbol)
    providers: list[tuple[str, Callable[[], FinancialMetrics]]] = [
        ("yahoo", _yahoo("metrics", lambda: yahoo.fetch_metrics(symbol)))
    ]
    if alpha_vantage.is_configured():
        providers.append(("alpha_vantage", lambda: alpha_vantage.fetch_metrics(symbol)))
    return _chain("metrics", providers)


@cached(_data_ttl)
def get_news(ticker: str, limit: int = 5) -> NewsFeed:
    symbol = normalize_ticker(ticker)
    limit = max(1, min(int(limit), 10))
    if _offline():
        return fixtures.news(symbol, limit)
    providers: list[tuple[str, Callable[[], NewsFeed]]] = [
        ("yahoo", _yahoo("news", lambda: yahoo.fetch_news(symbol, limit))),
        ("yahoo_rss", lambda: yahoo.fetch_news_rss(symbol, limit)),
    ]
    if alpha_vantage.is_configured():
        providers.append(("alpha_vantage", lambda: alpha_vantage.fetch_news(symbol, limit)))
    return _chain("news", providers)


@cached(_data_ttl)
def get_dividends(ticker: str) -> list[tuple[str, float]]:
    symbol = normalize_ticker(ticker)
    if _offline():
        return fixtures.dividends(symbol)
    try:
        return call_with_retry(lambda: yahoo.fetch_dividends(symbol), policy=_policy(), operation="yahoo.dividends")
    except Exception:  # noqa: BLE001 - dividends are optional context
        logger.warning("dividend history unavailable", extra={"ticker": symbol})
        return []


def list_filings(ticker: str, forms: tuple[str, ...], limit: int) -> FilingList:
    symbol = normalize_ticker(ticker)
    if _offline():
        return fixtures.filings(symbol, forms, limit)
    return sec_edgar.list_filings(symbol, forms, limit)


def get_filing_section(
    ticker: str, form: str, section: str, accession_number: str | None, max_chars: int
) -> FilingSection:
    symbol = normalize_ticker(ticker)
    if _offline():
        return fixtures.section(symbol, form, section, max_chars)
    return sec_edgar.get_section(symbol, form, section, accession_number, max_chars)


def get_xbrl_financials(ticker: str) -> XbrlFinancials:
    symbol = normalize_ticker(ticker)
    if _offline():
        return fixtures.xbrl(symbol)
    return sec_edgar.get_xbrl_financials(symbol)
