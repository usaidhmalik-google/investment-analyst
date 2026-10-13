"""Yahoo Finance adapter parsing (yfinance Ticker faked; RSS via respx)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest

from analyst.data import yahoo
from analyst.data.schemas import PriceBar


def frame(rows: list[tuple[str, float, float, float, float, float]]) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows])
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Volume": [r[5] for r in rows],
        },
        index=index,
    )


NVDA_INFO = {
    "longName": "NVIDIA Corporation",
    "shortName": "NVIDIA",
    "currentPrice": 128.5,
    "previousClose": 126.1,
    "currency": "USD",
    "dayHigh": 129.0,
    "dayLow": 125.5,
    "regularMarketVolume": 48_500_000,
    "averageVolume": 53_350_000.0,
    "marketCap": 3_151_234_567_890,
    "trailingPE": 48.2345,
    "forwardPE": 32.5,
    "fiftyTwoWeekHigh": 140.76,
    "fiftyTwoWeekLow": 86.62,
    "dividendRate": 0.04,
    "sector": "Technology",
    "industry": "Semiconductors",
}


class TestCoercion:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            (True, None),
            ("abc", None),
            (float("nan"), None),
            (float("inf"), None),
            ({}, None),
            ("1.23456", 1.2346),
            (2, 2.0),
        ],
    )
    def test_num(self, value, expected):
        assert yahoo.num(value) == expected

    def test_num_digits(self):
        assert yahoo.num(1.23456, 2) == 1.23
        assert yahoo.num(1.23456, None) == 1.23456
        assert yahoo.num(3_151_234_567_890.4, 0) == 3_151_234_567_890.0

    def test_pct_and_integer(self):
        assert yahoo.pct(0.12345) == 12.35
        assert yahoo.pct(None) is None
        assert yahoo.integer(12.9) == 12
        assert yahoo.integer(float("nan")) is None

    def test_now_iso_is_utc(self):
        assert yahoo.now_iso().endswith("+00:00")


class TestFetchQuote:
    def test_full_quote(self, fake_yf, make_ticker):
        fake_yf["NVDA"] = make_ticker(info=NVDA_INFO)
        q = yahoo.fetch_quote("NVDA")
        assert q.ticker == "NVDA" and q.company_name == "NVIDIA Corporation"
        assert q.price == 128.5 and q.previous_close == 126.1
        assert q.change == 2.4 and q.change_pct == 1.9
        assert q.volume == 48_500_000 and q.average_volume == 53_350_000
        assert q.market_cap == 3_151_234_567_890 and q.trailing_pe == 48.23 and q.forward_pe == 32.5
        assert q.dividend_yield_pct == 0.03
        assert q.source == "Yahoo Finance" and q.currency == "USD"
        assert (q.sector, q.industry) == ("Technology", "Semiconductors")

    def test_fallback_price_fields(self, fake_yf, make_ticker):
        info = {"regularMarketPrice": 50.0, "regularMarketPreviousClose": 40.0, "shortName": "Short", "volume": 7}
        fake_yf["X"] = make_ticker(info=info)
        q = yahoo.fetch_quote("X")
        assert q.price == 50.0 and q.change == 10.0 and q.change_pct == 25.0
        assert q.company_name == "Short" and q.volume == 7

    def test_fast_info_fallback(self, fake_yf, make_ticker):
        fake_yf["X"] = make_ticker(
            info={"currentPrice": float("nan")}, fast_info=SimpleNamespace(last_price=12.3456789)
        )
        q = yahoo.fetch_quote("X")
        assert q.price == 12.3457
        assert q.company_name == "X" and q.currency == "USD"
        assert q.previous_close is None and q.change is None and q.change_pct is None
        assert q.dividend_yield_pct is None

    def test_trailing_dividend_rate_fallback(self, fake_yf, make_ticker):
        fake_yf["KO"] = make_ticker(info={"currentPrice": 71.4, "trailingAnnualDividendRate": 2.04})
        assert yahoo.fetch_quote("KO").dividend_yield_pct == 2.86

    def test_nan_fields_become_none(self, fake_yf, make_ticker):
        info = {
            **NVDA_INFO,
            "trailingPE": float("nan"),
            "marketCap": None,
            "dayHigh": "n/a",
            "averageVolume": float("inf"),
        }
        fake_yf["NVDA"] = make_ticker(info=info)
        q = yahoo.fetch_quote("NVDA")
        assert q.trailing_pe is None and q.market_cap is None and q.day_high is None and q.average_volume is None

    def test_missing_price_raises_lookup_error(self, fake_yf, make_ticker):
        fake_yf["BAD"] = make_ticker(info={}, fast_info=SimpleNamespace(last_price=None))
        with pytest.raises(LookupError, match="no price for BAD"):
            yahoo.fetch_quote("BAD")

    def test_info_none(self, fake_yf, make_ticker):
        t = make_ticker()
        t.info = None
        fake_yf["BAD"] = t
        with pytest.raises(LookupError):
            yahoo.fetch_quote("BAD")


class TestFetchHistory:
    def test_parses_bars_and_summary(self, fake_yf, make_ticker):
        t = make_ticker(
            history=frame(
                [
                    ("2026-09-08", 100, 102, 99, 101, 1000),
                    ("2026-09-09", 101, 104, 100, 103, 3000),
                    ("2026-09-10", 103, 106, 102, 105.5, 2000),
                ]
            )
        )
        fake_yf["NVDA"] = t
        h = yahoo.fetch_history("NVDA", "5d")
        assert t.history_calls == [{"period": "5d", "interval": "1d", "auto_adjust": False}]
        assert [b.date for b in h.bars] == ["2026-09-08", "2026-09-09", "2026-09-10"]
        assert (h.start_date, h.end_date, h.start_close, h.end_close) == ("2026-09-08", "2026-09-10", 101, 105.5)
        assert h.change == 4.5 and h.change_pct == 4.46
        assert h.period_high == 106 and h.period_low == 99
        assert h.average_volume == 2000
        assert h.source == "Yahoo Finance" and h.period == "5d" and h.interval == "1d"

    def test_nan_handling(self, fake_yf, make_ticker):
        nan = float("nan")
        fake_yf["X"] = make_ticker(
            history=frame(
                [
                    ("2026-09-08", nan, nan, nan, nan, nan),  # dropped: no close
                    ("2026-09-09", nan, nan, nan, 50.0, nan),  # OHLC fall back to close, volume -> 0
                    ("2026-09-10", 50, 52, 49, 51.0, 10),
                ]
            )
        )
        h = yahoo.fetch_history("X", "5d")
        assert len(h.bars) == 2
        assert h.bars[0] == PriceBar(date="2026-09-09", open=50.0, high=50.0, low=50.0, close=50.0, volume=0)
        assert h.average_volume == 5

    @pytest.mark.parametrize("history", [None, pd.DataFrame()])
    def test_empty_history_raises(self, fake_yf, make_ticker, history):
        fake_yf["X"] = make_ticker(history=history)
        with pytest.raises(LookupError, match="no price history"):
            yahoo.fetch_history("X", "1mo")

    def test_all_nan_closes_raises(self, fake_yf, make_ticker):
        nan = float("nan")
        fake_yf["X"] = make_ticker(history=frame([("2026-09-08", 1, 1, 1, nan, 1)]))
        with pytest.raises(LookupError, match="No price bars"):
            yahoo.fetch_history("X", "1mo")

    def test_summarize_zero_start_close(self):
        bars = [
            PriceBar(date="d1", open=0, high=1, low=0, close=0),
            PriceBar(date="d2", open=1, high=2, low=1, close=2),
        ]
        assert yahoo.summarize_history("X", "5d", bars, "src").change_pct == 0.0


class TestFetchMetrics:
    INFO = {
        "totalRevenue": 60_922_000_000,
        "revenueGrowth": 1.224,
        "grossMargins": 0.75123,
        "operatingMargins": 0.615,
        "profitMargins": 0.534,
        "trailingEps": 2.6612,
        "forwardEps": 3.954,
        "returnOnEquity": 1.156,
        "debtToEquity": 41.2,
        "freeCashflow": 27_021_000_000.4,
        "priceToBook": 52.3461,
        "trailingPegRatio": 1.1234,
        "pegRatio": 9.9,
        "dividendRate": 0.04,
        "payoutRatio": 0.015,
        "targetMeanPrice": 145.004,
        "recommendationKey": "strong_buy",
        "numberOfAnalystOpinions": 45,
    }

    def test_full_metrics(self, fake_yf, make_ticker):
        fake_yf["NVDA"] = make_ticker(info=self.INFO)
        m = yahoo.fetch_metrics("NVDA")
        assert m.total_revenue == 60_922_000_000
        assert m.revenue_growth_pct == 122.4 and m.gross_margin_pct == 75.12
        assert m.operating_margin_pct == 61.5 and m.net_margin_pct == 53.4
        assert m.trailing_eps == 2.66 and m.forward_eps == 3.95
        assert m.return_on_equity_pct == 115.6
        assert m.debt_to_equity == 0.41  # Yahoo percent (41.2) normalised to a ratio
        assert m.free_cash_flow == 27_021_000_000
        assert m.price_to_book == 52.35 and m.peg_ratio == 1.12
        assert m.payout_ratio_pct == 1.5 and m.target_mean_price == 145.0
        assert m.analyst_consensus == "STRONG_BUY" and m.number_of_analysts == 45

    def test_peg_fallback_and_missing_fields(self, fake_yf, make_ticker):
        fake_yf["X"] = make_ticker(
            info={"trailingEps": 1.0, "pegRatio": 2.5, "recommendationKey": None, "debtToEquity": None}
        )
        m = yahoo.fetch_metrics("X")
        assert m.peg_ratio == 2.5
        assert m.debt_to_equity is None and m.analyst_consensus is None and m.total_revenue is None

    @pytest.mark.parametrize("info", [{}, None, {"currentPrice": 10.0}])
    def test_no_fundamentals_raises(self, fake_yf, make_ticker, info):
        t = make_ticker(info=info)
        t.info = info
        fake_yf["X"] = t
        with pytest.raises(LookupError, match="no fundamentals"):
            yahoo.fetch_metrics("X")


class TestFetchNews:
    def test_new_content_format(self, fake_yf, make_ticker):
        news = [
            {
                "id": "1",
                "content": {
                    "title": "Nvidia expands Blackwell production",
                    "pubDate": "2026-09-14T12:00:00Z",
                    "summary": "Summary text",
                    "provider": {"displayName": "Reuters"},
                    "canonicalUrl": {"url": "https://example.com/a"},
                    "clickThroughUrl": {"url": "https://example.com/click"},
                },
            },
            {"content": {"title": "", "provider": {}}},  # skipped: no title
            {
                "content": {
                    "title": "Second story",
                    "description": "Desc",
                    "canonicalUrl": None,
                    "clickThroughUrl": {"url": "https://example.com/b"},
                }
            },
        ]
        fake_yf["NVDA"] = make_ticker(news=news)
        feed = yahoo.fetch_news("NVDA", 5)
        assert [a.title for a in feed.articles] == ["Nvidia expands Blackwell production", "Second story"]
        a, b = feed.articles
        assert (a.publisher, a.url, a.published, a.summary) == (
            "Reuters",
            "https://example.com/a",
            "2026-09-14T12:00:00Z",
            "Summary text",
        )
        assert (b.publisher, b.url, b.summary) == (None, "https://example.com/b", "Desc")
        assert feed.source == "Yahoo Finance" and feed.ticker == "NVDA"

    def test_legacy_format(self, fake_yf, make_ticker):
        news = [
            {
                "title": "Legacy",
                "publisher": "Bloomberg",
                "link": "https://l.example",
                "providerPublishTime": 1_757_851_200,
            }
        ]
        fake_yf["X"] = make_ticker(news=news)
        (article,) = yahoo.fetch_news("X", 5).articles
        assert article.publisher == "Bloomberg" and article.url == "https://l.example"
        assert article.published == "2025-09-14T12:00:00+00:00"

    def test_limit_applied(self, fake_yf, make_ticker):
        fake_yf["X"] = make_ticker(news=[{"title": f"Story {i}"} for i in range(8)])
        assert len(yahoo.fetch_news("X", 3).articles) == 3

    @pytest.mark.parametrize("news", [None, [], [{"content": {"title": None}}]])
    def test_empty_raises(self, fake_yf, make_ticker, news):
        fake_yf["X"] = make_ticker(news=news)
        with pytest.raises(LookupError, match="no news"):
            yahoo.fetch_news("X", 5)


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Yahoo</title>
<item><title> NVDA hits record </title><link>https://example.com/1</link>
<description>Shares rose 3.2%.</description><pubDate>Mon, 14 Sep 2026 12:30:00 +0200</pubDate></item>
<item><title></title><link>https://example.com/skip</link></item>
<item><title>Bad date</title><pubDate>not a date</pubDate></item>
<item><title>Third</title></item>
</channel></rss>"""


class TestFetchNewsRss:
    def test_parses_feed(self, mock_http):
        route = mock_http.get(yahoo.RSS_URL).mock(return_value=httpx.Response(200, text=RSS))
        feed = yahoo.fetch_news_rss("NVDA", 5)
        request = route.calls.last.request
        assert request.url.params["s"] == "NVDA" and request.url.params["region"] == "US"
        assert "MALIK-Investment-Analyst" in request.headers["User-Agent"]
        assert [a.title for a in feed.articles] == ["NVDA hits record", "Bad date", "Third"]
        first, bad, third = feed.articles
        assert first.published == "2026-09-14T10:30:00+00:00"
        assert first.url == "https://example.com/1" and first.summary == "Shares rose 3.2%."
        assert first.publisher == "Yahoo Finance"
        assert bad.published == "not a date"
        assert third.url is None and third.summary is None and third.published is None

    def test_limit(self, mock_http):
        mock_http.get(yahoo.RSS_URL).mock(return_value=httpx.Response(200, text=RSS))
        assert len(yahoo.fetch_news_rss("NVDA", 1).articles) == 1

    def test_empty_feed_raises(self, mock_http):
        mock_http.get(yahoo.RSS_URL).mock(return_value=httpx.Response(200, text="<rss><channel></channel></rss>"))
        with pytest.raises(LookupError, match="RSS returned no news"):
            yahoo.fetch_news_rss("NVDA", 5)

    def test_retries_on_429_then_succeeds(self, mock_http):
        route = mock_http.get(yahoo.RSS_URL).mock(
            side_effect=[httpx.Response(429), httpx.Response(503), httpx.Response(200, text=RSS)]
        )
        assert len(yahoo.fetch_news_rss("NVDA", 5).articles) == 3
        assert route.call_count == 3


class TestFetchDividends:
    def test_series(self, fake_yf, make_ticker):
        series = pd.Series(
            [0.51, 0.485], index=pd.DatetimeIndex([pd.Timestamp("2025-03-14"), pd.Timestamp("2025-06-13")])
        )
        fake_yf["KO"] = make_ticker(dividends=series)
        assert yahoo.fetch_dividends("KO") == [("2025-03-14", 0.51), ("2025-06-13", 0.485)]

    @pytest.mark.parametrize("series", [None, pd.Series([], dtype=float)])
    def test_empty(self, fake_yf, make_ticker, series):
        fake_yf["X"] = make_ticker(dividends=series)
        assert yahoo.fetch_dividends("X") == []

    def test_values_are_python_floats(self, fake_yf, make_ticker):
        series = pd.Series([0.25], index=pd.DatetimeIndex([pd.Timestamp("2025-01-01")]))
        fake_yf["X"] = make_ticker(dividends=series)
        ((_, amount),) = yahoo.fetch_dividends("X")
        assert type(amount) is float and not math.isnan(amount)
