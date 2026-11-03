"""Provider facade: offline fixtures, Yahoo → Yahoo RSS → Alpha Vantage fallback chain, caching, validation."""

from __future__ import annotations

import pandas as pd
import pytest

from analyst.config import get_settings
from analyst.data import alpha_vantage, fixtures, market, sec_edgar, yahoo
from analyst.data.schemas import NewsArticle, NewsFeed
from analyst.tools.resilience import DataProviderError


class Recorder:
    """Callable that returns/raises queued results and counts calls."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        item = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(item, BaseException):
            raise item
        return item


def feed(source: str) -> NewsFeed:
    return NewsFeed(ticker="NVDA", articles=[NewsArticle(title=f"from {source}")], source=source, as_of="now")


@pytest.fixture
def av_on(monkeypatch):
    monkeypatch.setattr(alpha_vantage, "is_configured", lambda: True)


class TestNormalizeTicker:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("nvda", "NVDA"), (" $aapl ", "AAPL"), ("BRK.B", "BRK.B"), ("^GSPC", "^GSPC"), ("EURUSD=X", "EURUSD=X")],
    )
    def test_valid(self, raw, expected):
        assert market.normalize_ticker(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", None, "TOOLONGTICKER", "NV DA", "NVDA;DROP", "<script>"])
    def test_invalid(self, raw):
        with pytest.raises(ValueError, match="Invalid ticker"):
            market.normalize_ticker(raw)


class TestOffline:
    def test_offline_mode_uses_fixtures(self, monkeypatch):
        monkeypatch.setattr(yahoo, "fetch_quote", lambda s: pytest.fail("network provider used offline"))
        q = market.get_quote("nvda")
        assert q.source == "Offline Fixture" and q.price == 128.5
        h = market.get_history("NVDA", "5d")
        assert h.source == "Offline Fixture" and len(h.bars) == 5 and h.end_close == 128.5
        assert market.get_metrics("NVDA").source == "Offline Fixture"
        assert len(market.get_news("NVDA", 2).articles) == 2
        assert market.get_dividends("KO")[0] == ("2020-02-15", round(2.04 / 1.05**6 / 4, 4))
        assert market.list_filings("NVDA", ("10-K", "8-K"), 5).filings[1].form == "8-K"
        sec = market.get_filing_section("NVDA", "10-K", "risk_factors", None, 500)
        assert sec.truncated is True and len(sec.text) == 500
        assert market.get_xbrl_financials("NVDA").annual["revenue"].value == 60.92e9

    def test_unknown_offline_ticker(self):
        with pytest.raises(LookupError, match="No offline fixture for ZZZZ"):
            market.get_quote("ZZZZ")

    def test_news_limit_clamped(self):
        assert len(market.get_news("NVDA", 0).articles) == 1
        assert len(market.get_news("NVDA", 99).articles) == 3

    def test_invalid_period(self):
        with pytest.raises(ValueError, match="period must be one of"):
            market.get_history("NVDA", "10y")

    def test_fixture_history_is_deterministic(self):
        a = fixtures.history("AAPL", "1y")
        b = fixtures.history("aapl", "1y")
        assert a.bars == b.bars and len(a.bars) == 252
        assert all(bar.low <= bar.close <= bar.high for bar in a.bars)
        assert fixtures.supported_tickers() == ["AAPL", "KO", "MSFT", "NVDA"]


@pytest.mark.usefixtures("online")
class TestFallbackChain:
    def test_yahoo_success(self, monkeypatch, av_on):
        q = fixtures.quote("NVDA")
        y = Recorder(q)
        a = Recorder(AssertionError("must not fall back"))
        monkeypatch.setattr(yahoo, "fetch_quote", y)
        monkeypatch.setattr(alpha_vantage, "fetch_quote", a)
        assert market.get_quote("nvda") is q
        assert y.calls == [("NVDA",)] and a.calls == []

    def test_yahoo_rate_limited_retried_before_fallback(self, monkeypatch):
        YFRateLimitError = type("YFRateLimitError", (Exception,), {})
        q = fixtures.quote("NVDA")
        y = Recorder(YFRateLimitError("Too Many Requests"), q)
        monkeypatch.setattr(yahoo, "fetch_quote", y)
        assert market.get_quote("NVDA") is q
        assert len(y.calls) == 2

    def test_falls_back_to_alpha_vantage(self, monkeypatch, av_on):
        q = fixtures.quote("NVDA")
        y = Recorder(LookupError("no price"))
        monkeypatch.setattr(yahoo, "fetch_quote", y)
        monkeypatch.setattr(alpha_vantage, "fetch_quote", Recorder(q))
        assert market.get_quote("NVDA") is q
        assert len(y.calls) == 1  # LookupError is permanent: no Yahoo retries

    def test_all_fail_raises_data_provider_error(self, monkeypatch, av_on):
        monkeypatch.setattr(yahoo, "fetch_quote", Recorder(LookupError("yahoo empty")))
        monkeypatch.setattr(alpha_vantage, "fetch_quote", Recorder(RuntimeError("av down")))
        with pytest.raises(DataProviderError) as info:
            market.get_quote("NVDA")
        assert "All providers failed for quote" in str(info.value)
        assert "yahoo: yahoo empty" in str(info.value) and "alpha_vantage: av down" in str(info.value)

    def test_no_alpha_vantage_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(yahoo, "fetch_quote", Recorder(LookupError("nope")))
        monkeypatch.setattr(alpha_vantage, "fetch_quote", Recorder(AssertionError("unconfigured provider used")))
        with pytest.raises(DataProviderError, match=r"yahoo: nope$"):
            market.get_quote("NVDA")

    def test_yahoo_exhausts_retries_then_falls_back(self, monkeypatch, av_on):
        q = fixtures.quote("NVDA")
        y = Recorder(TimeoutError("slow"))
        monkeypatch.setattr(yahoo, "fetch_quote", y)
        monkeypatch.setattr(alpha_vantage, "fetch_quote", Recorder(q))
        assert market.get_quote("NVDA") is q
        assert len(y.calls) == get_settings().http_max_retries + 1

    def test_news_chain_yahoo_then_rss_then_av(self, monkeypatch, av_on):
        monkeypatch.setattr(yahoo, "fetch_news", Recorder(LookupError("empty")))
        rss = Recorder(feed("rss"))
        monkeypatch.setattr(yahoo, "fetch_news_rss", rss)
        monkeypatch.setattr(alpha_vantage, "fetch_news", Recorder(AssertionError("too far")))
        assert market.get_news("NVDA", 3).source == "rss"
        assert rss.calls == [("NVDA", 3)]

    def test_news_chain_reaches_alpha_vantage(self, monkeypatch, av_on):
        monkeypatch.setattr(yahoo, "fetch_news", Recorder(LookupError("empty")))
        monkeypatch.setattr(yahoo, "fetch_news_rss", Recorder(LookupError("rss empty")))
        monkeypatch.setattr(alpha_vantage, "fetch_news", Recorder(feed("av")))
        assert market.get_news("NVDA", 3).source == "av"

    def test_news_all_fail(self, monkeypatch):
        monkeypatch.setattr(yahoo, "fetch_news", Recorder(LookupError("a")))
        monkeypatch.setattr(yahoo, "fetch_news_rss", Recorder(LookupError("b")))
        with pytest.raises(DataProviderError, match="news: yahoo: a; yahoo_rss: b"):
            market.get_news("NVDA", 3)

    def test_history_fallback(self, monkeypatch, av_on):
        h = fixtures.history("NVDA", "1mo")
        monkeypatch.setattr(yahoo, "fetch_history", Recorder(LookupError("empty")))
        av = Recorder(h)
        monkeypatch.setattr(alpha_vantage, "fetch_history", av)
        assert market.get_history("NVDA", "1mo") is h
        assert av.calls == [("NVDA", "1mo")]

    def test_metrics_fallback(self, monkeypatch, av_on):
        m = fixtures.metrics("NVDA")
        monkeypatch.setattr(yahoo, "fetch_metrics", Recorder(LookupError("empty")))
        monkeypatch.setattr(alpha_vantage, "fetch_metrics", Recorder(m))
        assert market.get_metrics("NVDA") is m

    def test_history_and_metrics_yahoo_only(self, monkeypatch):
        h, m = fixtures.history("NVDA", "5d"), fixtures.metrics("NVDA")
        monkeypatch.setattr(yahoo, "fetch_history", Recorder(h))
        monkeypatch.setattr(yahoo, "fetch_metrics", Recorder(m))
        assert market.get_history("NVDA", "5d") is h
        assert market.get_metrics("NVDA") is m

    def test_dividends_success_and_degrade(self, monkeypatch):
        monkeypatch.setattr(yahoo, "fetch_dividends", Recorder([("2025-01-01", 0.5)]))
        assert market.get_dividends("KO") == [("2025-01-01", 0.5)]
        monkeypatch.setattr(yahoo, "fetch_dividends", Recorder(RuntimeError("down")))
        assert market.get_dividends("PEP") == []

    def test_sec_functions_delegate(self, monkeypatch):
        seen = []
        monkeypatch.setattr(sec_edgar, "list_filings", lambda *a: seen.append(("list", a)) or "L")
        monkeypatch.setattr(sec_edgar, "get_section", lambda *a: seen.append(("section", a)) or "S")
        monkeypatch.setattr(sec_edgar, "get_xbrl_financials", lambda *a: seen.append(("xbrl", a)) or "X")
        assert market.list_filings("nvda", ("10-K",), 3) == "L"
        assert market.get_filing_section("nvda", "10-K", "mdna", "acc", 2000) == "S"
        assert market.get_xbrl_financials("nvda") == "X"
        assert seen == [
            ("list", ("NVDA", ("10-K",), 3)),
            ("section", ("NVDA", "10-K", "mdna", "acc", 2000)),
            ("xbrl", ("NVDA",)),
        ]

    def test_real_yahoo_adapter_through_facade(self, fake_yf, make_ticker):
        fake_yf["NVDA"] = make_ticker(info={"currentPrice": 128.5, "previousClose": 126.1})
        fake_yf["MSFT"] = make_ticker(
            history=pd.DataFrame(
                {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10]},
                index=pd.DatetimeIndex([pd.Timestamp("2026-09-15")]),
            )
        )
        assert market.get_quote("NVDA").change == 2.4
        assert market.get_history("MSFT", "5d").end_close == 1.5


@pytest.mark.usefixtures("online")
class TestCaching:
    def test_second_call_served_from_cache(self, monkeypatch):
        y = Recorder(fixtures.quote("NVDA"))
        monkeypatch.setattr(yahoo, "fetch_quote", y)
        first = market.get_quote("NVDA")
        second = market.get_quote("NVDA")
        assert first is second and len(y.calls) == 1

    def test_cache_key_includes_arguments(self, monkeypatch):
        y = Recorder(fixtures.history("NVDA", "5d"))
        monkeypatch.setattr(yahoo, "fetch_history", y)
        market.get_history("NVDA", "5d")
        market.get_history("NVDA", "1mo")
        market.get_history("NVDA", "5d")
        assert len(y.calls) == 2

    def test_failures_not_cached(self, monkeypatch):
        y = Recorder(LookupError("transient"), fixtures.quote("NVDA"))
        monkeypatch.setattr(yahoo, "fetch_quote", y)
        with pytest.raises(DataProviderError):
            market.get_quote("NVDA")
        assert market.get_quote("NVDA").price == 128.5

    def test_quote_ttl_from_settings(self, monkeypatch):
        monkeypatch.setenv("QUOTE_CACHE_TTL_SECONDS", "0")
        get_settings.cache_clear()
        y = Recorder(fixtures.quote("NVDA"))
        monkeypatch.setattr(yahoo, "fetch_quote", y)
        market.get_quote("NVDA")
        assert market.get_quote.cache.ttl == 0
