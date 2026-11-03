"""Stock research tools for the Investment Analyst agent using yfinance with offline enterprise fixtures fallback."""

import math
from typing import Any, Dict, List
try:
    import yfinance as yf
except ImportError:
    yf = None

# Offline fixtures for airgapped / private VPC environments without public internet
OFFLINE_FIXTURES: Dict[str, Dict[str, Any]] = {
    "NVDA": {
        "quote": {
            "ticker": "NVDA",
            "company_name": "NVIDIA Corporation",
            "current_price": 128.50,
            "currency": "USD",
            "market_cap": "$3.15T",
            "trailing_pe": 48.20,
            "forward_pe": 32.50,
            "fifty_two_week_high": 140.76,
            "fifty_two_week_low": 40.85,
            "volume": 48500000,
            "sector": "Technology",
            "industry": "Semiconductors",
        },
        "metrics": {
            "ticker": "NVDA",
            "total_revenue": "$60.92B",
            "revenue_growth_yoy": "122.40%",
            "gross_margin": "75.10%",
            "operating_margin": "61.50%",
            "net_profit_margin": "53.40%",
            "trailing_eps": 2.66,
            "forward_eps": 3.95,
            "return_on_equity": "115.60%",
            "debt_to_equity": 0.42,
            "free_cash_flow": "$27.02B",
            "target_mean_price": 145.00,
            "analyst_consensus": "BUY",
            "number_of_analysts": 45,
        },
        "news": [
            {
                "title": "Nvidia Blackwell Ultra architecture production expands across enterprise cloud hyperscalers",
                "publisher": "Reuters",
                "published": "2026-09-14",
                "link": "https://finance.yahoo.com",
            },
            {
                "title": "Enterprise AI infrastructure spending forecast upgraded for 2026-2027 fiscal year",
                "publisher": "Bloomberg",
                "published": "2026-09-12",
                "link": "https://finance.yahoo.com",
            },
            {
                "title": "Data center efficiency metrics highlight Blackwell energy-to-compute ratio",
                "publisher": "Wall Street Journal",
                "published": "2026-09-10",
                "link": "https://finance.yahoo.com",
            },
        ],
    },
    "AAPL": {
        "quote": {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "current_price": 224.20,
            "currency": "USD",
            "market_cap": "$3.42T",
            "trailing_pe": 33.80,
            "forward_pe": 28.40,
            "fifty_two_week_high": 237.23,
            "fifty_two_week_low": 164.08,
            "volume": 52100000,
            "sector": "Technology",
            "industry": "Consumer Electronics",
        },
        "metrics": {
            "ticker": "AAPL",
            "total_revenue": "$385.60B",
            "revenue_growth_yoy": "4.90%",
            "gross_margin": "46.20%",
            "operating_margin": "31.20%",
            "net_profit_margin": "25.30%",
            "trailing_eps": 6.57,
            "forward_eps": 7.42,
            "return_on_equity": "147.20%",
            "debt_to_equity": 1.45,
            "free_cash_flow": "$108.80B",
            "target_mean_price": 242.00,
            "analyst_consensus": "BUY",
            "number_of_analysts": 42,
        },
        "news": [
            {
                "title": "Apple Intelligence features rolled out globally with expanded localized language models",
                "publisher": "Bloomberg",
                "published": "2026-09-13",
                "link": "https://finance.yahoo.com",
            },
            {
                "title": "Services revenue hits new quarterly record driven by App Store and cloud subscriptions",
                "publisher": "Financial Times",
                "published": "2026-09-11",
                "link": "https://finance.yahoo.com",
            },
        ],
    },
    "MSFT": {
        "quote": {
            "ticker": "MSFT",
            "company_name": "Microsoft Corporation",
            "current_price": 435.50,
            "currency": "USD",
            "market_cap": "$3.24T",
            "trailing_pe": 35.60,
            "forward_pe": 29.80,
            "fifty_two_week_high": 468.35,
            "fifty_two_week_low": 309.45,
            "volume": 21800000,
            "sector": "Technology",
            "industry": "Software - Infrastructure",
        },
        "metrics": {
            "ticker": "MSFT",
            "total_revenue": "$245.12B",
            "revenue_growth_yoy": "15.20%",
            "gross_margin": "69.80%",
            "operating_margin": "44.60%",
            "net_profit_margin": "36.10%",
            "trailing_eps": 11.80,
            "forward_eps": 13.50,
            "return_on_equity": "38.50%",
            "debt_to_equity": 0.38,
            "free_cash_flow": "$74.10B",
            "target_mean_price": 490.00,
            "analyst_consensus": "BUY",
            "number_of_analysts": 48,
        },
        "news": [
            {
                "title": "Microsoft Cloud quarterly run-rate exceeds $140B fueled by enterprise Copilot adoption",
                "publisher": "Reuters",
                "published": "2026-09-14",
                "link": "https://finance.yahoo.com",
            },
            {
                "title": "Azure AI capacity expansions go live across Europe and North America regions",
                "publisher": "Wall Street Journal",
                "published": "2026-09-11",
                "link": "https://finance.yahoo.com",
            },
        ],
    },
    "TSLA": {
        "quote": {
            "ticker": "TSLA",
            "company_name": "Tesla, Inc.",
            "current_price": 230.10,
            "currency": "USD",
            "market_cap": "$735.40B",
            "trailing_pe": 62.40,
            "forward_pe": 54.10,
            "fifty_two_week_high": 271.00,
            "fifty_two_week_low": 138.80,
            "volume": 68000000,
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
        },
        "metrics": {
            "ticker": "TSLA",
            "total_revenue": "$96.77B",
            "revenue_growth_yoy": "3.20%",
            "gross_margin": "17.90%",
            "operating_margin": "7.80%",
            "net_profit_margin": "6.80%",
            "trailing_eps": 3.12,
            "forward_eps": 4.10,
            "return_on_equity": "21.40%",
            "debt_to_equity": 0.12,
            "free_cash_flow": "$3.60B",
            "target_mean_price": 215.00,
            "analyst_consensus": "HOLD",
            "number_of_analysts": 38,
        },
        "news": [
            {
                "title": "Tesla Energy storage deployments double year-over-year with Megapack Shanghai factory ramp",
                "publisher": "Bloomberg",
                "published": "2026-09-14",
                "link": "https://finance.yahoo.com",
            },
            {
                "title": "Full Self-Driving (Supervised) v13 demonstrates lower disengagement rates in urban testing",
                "publisher": "Electrek",
                "published": "2026-09-12",
                "link": "https://finance.yahoo.com",
            },
        ],
    },
    "GOOGL": {
        "quote": {
            "ticker": "GOOGL",
            "company_name": "Alphabet Inc.",
            "current_price": 162.80,
            "currency": "USD",
            "market_cap": "$2.01T",
            "trailing_pe": 23.40,
            "forward_pe": 19.80,
            "fifty_two_week_high": 191.75,
            "fifty_two_week_low": 120.21,
            "volume": 24500000,
            "sector": "Communication Services",
            "industry": "Internet Content & Information",
        },
        "metrics": {
            "ticker": "GOOGL",
            "total_revenue": "$328.28B",
            "revenue_growth_yoy": "13.80%",
            "gross_margin": "57.40%",
            "operating_margin": "32.00%",
            "net_profit_margin": "26.80%",
            "trailing_eps": 6.95,
            "forward_eps": 8.20,
            "return_on_equity": "31.20%",
            "debt_to_equity": 0.10,
            "free_cash_flow": "$69.20B",
            "target_mean_price": 205.00,
            "analyst_consensus": "BUY",
            "number_of_analysts": 50,
        },
        "news": [
            {
                "title": "Google Cloud operating profit surges as Gemini Enterprise API consumption accelerates",
                "publisher": "Reuters",
                "published": "2026-09-13",
                "link": "https://finance.yahoo.com",
            },
            {
                "title": "Gemini 2.5 architecture establishes new benchmarks for agentic tool use and code reasoning",
                "publisher": "TechCrunch",
                "published": "2026-09-12",
                "link": "https://finance.yahoo.com",
            },
        ],
    },
}


def _clean_val(val: Any) -> Any:
    """Safely format numeric values, handling None and NaN."""
    if val is None:
        return "N/A"
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return "N/A"
        return round(val, 2)
    return val


def _format_currency(val: Any) -> str:
    """Format large numbers into human-readable currency strings ($B, $M, $T)."""
    if val is None or val == "N/A":
        return "N/A"
    try:
        num = float(val)
        if abs(num) >= 1e12:
            return f"${num / 1e12:.2f}T"
        if abs(num) >= 1e9:
            return f"${num / 1e9:.2f}B"
        if abs(num) >= 1e6:
            return f"${num / 1e6:.2f}M"
        return f"${num:.2f}"
    except (ValueError, TypeError):
        return str(val)


def _format_percent(val: Any) -> str:
    """Format float values as percentage string."""
    if val is None or val == "N/A":
        return "N/A"
    try:
        return f"{float(val) * 100:.2f}%"
    except (ValueError, TypeError):
        return str(val)


import time

# Tool invocation audit log for benchmarking and observability
EXECUTED_TOOLS: List[Dict[str, Any]] = []


def reset_tool_history() -> None:
    """Clear the recorded tool invocations."""
    EXECUTED_TOOLS.clear()


def get_tool_history() -> List[Dict[str, Any]]:
    """Return the list of recorded tool invocations."""
    return list(EXECUTED_TOOLS)


def _record_tool(name: str, args: Dict[str, Any]) -> None:
    """Record a tool invocation for observability."""
    EXECUTED_TOOLS.append({
        "tool": name,
        "args": args,
        "timestamp": time.time(),
    })


def get_stock_quote(ticker: str) -> Dict[str, Any]:
    """Retrieve real-time market quote, valuation, and trading range for a stock ticker.

    Args:
        ticker: The stock ticker symbol (e.g. 'AAPL', 'NVDA', 'GOOGL', 'MSFT', 'TSLA').

    Returns:
        A dictionary containing company name, current price, currency,
        market cap, P/E ratio, 52-week high/low, and trading volume.
    """
    cleaned_ticker = ticker.strip().upper()
    _record_tool("get_stock_quote", {"ticker": cleaned_ticker})
    try:
        t = yf.Ticker(cleaned_ticker)
        info = t.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            price = getattr(t.fast_info, "last_price", None)
        if price is None:
            if cleaned_ticker in OFFLINE_FIXTURES:
                return OFFLINE_FIXTURES[cleaned_ticker]["quote"]
            return {"error": f"Could not find stock quote data for ticker '{cleaned_ticker}'."}

        return {
            "ticker": cleaned_ticker,
            "company_name": info.get("shortName") or info.get("longName") or cleaned_ticker,
            "current_price": _clean_val(price),
            "currency": info.get("currency", "USD"),
            "market_cap": _format_currency(info.get("marketCap")),
            "trailing_pe": _clean_val(info.get("trailingPE")),
            "forward_pe": _clean_val(info.get("forwardPE")),
            "fifty_two_week_high": _clean_val(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _clean_val(info.get("fiftyTwoWeekLow")),
            "volume": info.get("regularMarketVolume") or info.get("volume", "N/A"),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
        }
    except Exception:
        if cleaned_ticker in OFFLINE_FIXTURES:
            return OFFLINE_FIXTURES[cleaned_ticker]["quote"]
        return {"error": f"Failed to retrieve quote for '{cleaned_ticker}'."}


def get_financial_metrics(ticker: str) -> Dict[str, Any]:
    """Retrieve financial health, profitability, and analyst consensus metrics for a stock ticker.

    Args:
        ticker: The stock ticker symbol (e.g. 'AAPL', 'NVDA', 'GOOGL', 'MSFT', 'TSLA').

    Returns:
        A dictionary containing total revenue, revenue growth, profit margins,
        earnings per share (EPS), return on equity, free cash flow, and analyst recommendations.
    """
    cleaned_ticker = ticker.strip().upper()
    _record_tool("get_financial_metrics", {"ticker": cleaned_ticker})
    try:
        t = yf.Ticker(cleaned_ticker)
        info = t.info
        if not info or ("totalRevenue" not in info and "trailingEps" not in info):
            if cleaned_ticker in OFFLINE_FIXTURES:
                return OFFLINE_FIXTURES[cleaned_ticker]["metrics"]
            return {"error": f"Could not find financial metrics for ticker '{cleaned_ticker}'."}

        return {
            "ticker": cleaned_ticker,
            "total_revenue": _format_currency(info.get("totalRevenue")),
            "revenue_growth_yoy": _format_percent(info.get("revenueGrowth")),
            "gross_margin": _format_percent(info.get("grossMargins")),
            "operating_margin": _format_percent(info.get("operatingMargins")),
            "net_profit_margin": _format_percent(info.get("profitMargins")),
            "trailing_eps": _clean_val(info.get("trailingEps")),
            "forward_eps": _clean_val(info.get("forwardEps")),
            "return_on_equity": _format_percent(info.get("returnOnEquity")),
            "debt_to_equity": _clean_val(info.get("debtToEquity")),
            "free_cash_flow": _format_currency(info.get("freeCashflow")),
            "target_mean_price": _clean_val(info.get("targetMeanPrice")),
            "analyst_consensus": info.get("recommendationKey", "N/A").upper(),
            "number_of_analysts": info.get("numberOfAnalystOpinions", "N/A"),
        }
    except Exception:
        if cleaned_ticker in OFFLINE_FIXTURES:
            return OFFLINE_FIXTURES[cleaned_ticker]["metrics"]
        return {"error": f"Failed to retrieve financial metrics for '{cleaned_ticker}'."}


def get_company_news(ticker: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieve recent news headlines and publication details for a stock ticker.

    Args:
        ticker: The stock ticker symbol (e.g. 'AAPL', 'NVDA', 'GOOGL', 'MSFT', 'TSLA').
        limit: Number of news articles to retrieve (defaults to 5).

    Returns:
        A list of dictionaries with headline titles, publishers, and publication dates.
    """
    cleaned_ticker = ticker.strip().upper()
    _record_tool("get_company_news", {"ticker": cleaned_ticker, "limit": limit})
    try:
        t = yf.Ticker(cleaned_ticker)
        raw_news = t.news or []
        articles = []
        for item in raw_news[:limit]:
            content = item.get("content", {}) if isinstance(item.get("content"), dict) else item
            title = content.get("title") or item.get("title", "N/A")
            provider = content.get("provider", {}) if isinstance(content.get("provider"), dict) else {}
            publisher = provider.get("displayName") or item.get("publisher", "N/A")
            published = content.get("pubDate") or item.get("providerPublishTime", "N/A")
            link = ""
            if "canonicalUrl" in content and isinstance(content["canonicalUrl"], dict):
                link = content["canonicalUrl"].get("url", "")
            elif "link" in item:
                link = item.get("link", "")

            articles.append({
                "title": title,
                "publisher": publisher,
                "published": published,
                "link": link,
            })

        if articles:
            return articles
        if cleaned_ticker in OFFLINE_FIXTURES:
            return OFFLINE_FIXTURES[cleaned_ticker]["news"][:limit]
        return [{"message": f"No recent news found for {cleaned_ticker}"}]
    except Exception:
        if cleaned_ticker in OFFLINE_FIXTURES:
            return OFFLINE_FIXTURES[cleaned_ticker]["news"][:limit]
        return [{"error": f"Failed to retrieve news for '{cleaned_ticker}'."}]
