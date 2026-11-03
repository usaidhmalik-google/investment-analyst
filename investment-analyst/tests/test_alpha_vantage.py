"""Alpha Vantage adapter + secret resolution (HTTP mocked with respx)."""

from __future__ import annotations

import httpx
import pytest

from analyst.config import get_settings
from analyst.data import alpha_vantage, secrets
from analyst.tools.resilience import DataProviderError, RateLimitedError


@pytest.fixture
def av_key(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "demo-key")
    get_settings.cache_clear()
    secrets.get_alpha_vantage_key.cache_clear()


@pytest.fixture
def av(mock_http, av_key):
    """Route Alpha Vantage requests by ``function`` param to queued payloads."""
    queues: dict[str, list] = {}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        fn = request.url.params["function"]
        item = queues[fn].pop(0) if len(queues[fn]) > 1 else queues[fn][0]
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)

    mock_http.get(alpha_vantage.BASE_URL).mock(side_effect=handler)
    return queues, seen


class TestConfiguration:
    def test_not_configured(self):
        assert alpha_vantage.is_configured() is False
        with pytest.raises(DataProviderError, match="not configured"):
            alpha_vantage._query("GLOBAL_QUOTE", symbol="X")

    def test_env_key(self, av_key):
        assert alpha_vantage.is_configured() is True
        assert secrets.get_alpha_vantage_key() == "demo-key"

    def test_secret_manager_key(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_SECRET", "projects/p/secrets/av/versions/latest")
        get_settings.cache_clear()
        seen = []
        monkeypatch.setattr(secrets, "access_secret", lambda name: seen.append(name) or "from-sm")
        assert secrets.get_alpha_vantage_key() == "from-sm"
        assert seen == ["projects/p/secrets/av/versions/latest"]

    def test_secret_manager_failure_degrades(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_SECRET", "projects/p/secrets/av/versions/latest")
        get_settings.cache_clear()

        def boom(name):
            raise PermissionError("denied")

        monkeypatch.setattr(secrets, "access_secret", boom)
        assert secrets.get_alpha_vantage_key() is None

    def test_access_secret_uses_client(self, monkeypatch):
        from google.cloud import secretmanager

        class FakeClient:
            def access_secret_version(self, name):
                assert name == "projects/p/secrets/s/versions/1"
                payload = type("P", (), {"data": b"  secret-value\n"})()
                return type("R", (), {"payload": payload})()

        monkeypatch.setattr(secretmanager, "SecretManagerServiceClient", FakeClient)
        assert secrets.access_secret("projects/p/secrets/s/versions/1") == "secret-value"


class TestQuery:
    def test_sends_function_symbol_and_key(self, av):
        queues, seen = av
        queues["GLOBAL_QUOTE"] = [{"Global Quote": {"05. price": "10.0"}}]
        alpha_vantage._query("GLOBAL_QUOTE", symbol="AAPL")
        params = seen[0].url.params
        assert params["function"] == "GLOBAL_QUOTE" and params["symbol"] == "AAPL" and params["apikey"] == "demo-key"

    def test_rate_limit_note_retried_then_succeeds(self, av):
        queues, seen = av
        queues["GLOBAL_QUOTE"] = [
            {"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."},
            {"Information": "rate limited"},
            {"Global Quote": {"05. price": "10.0"}},
        ]
        assert alpha_vantage.fetch_quote("AAPL").price == 10.0
        assert len(seen) == 3

    def test_rate_limit_exhausted_raises(self, av):
        queues, seen = av
        queues["GLOBAL_QUOTE"] = [{"Note": "rate limit"}]
        with pytest.raises(RateLimitedError, match="rate limit"):
            alpha_vantage.fetch_quote("AAPL")
        assert len(seen) == get_settings().http_max_retries + 1

    def test_information_with_data_is_not_rate_limit(self, av):
        queues, _ = av
        queues["OVERVIEW"] = [{"Information": "note", "Symbol": "AAPL"}]
        assert alpha_vantage._query("OVERVIEW", symbol="AAPL")["Symbol"] == "AAPL"

    def test_error_message_is_permanent(self, av):
        queues, seen = av
        queues["GLOBAL_QUOTE"] = [{"Error Message": "Invalid API call."}]
        with pytest.raises(DataProviderError, match="Invalid API call"):
            alpha_vantage.fetch_quote("ZZZZ")
        assert len(seen) == 1

    def test_http_500_retried(self, av):
        queues, seen = av
        queues["GLOBAL_QUOTE"] = [httpx.Response(500), {"Global Quote": {"05. price": "11"}}]
        assert alpha_vantage.fetch_quote("AAPL").price == 11.0
        assert len(seen) == 2


class TestParsers:
    def test_quote(self, av):
        queues, _ = av
        queues["GLOBAL_QUOTE"] = [
            {
                "Global Quote": {
                    "01. symbol": "AAPL",
                    "03. high": "226.00",
                    "04. low": "222.10",
                    "05. price": "224.2000",
                    "06. volume": "52100000",
                    "07. latest trading day": "2026-09-15",
                    "08. previous close": "225.0500",
                    "09. change": "-0.8500",
                    "10. change percent": "-0.3777%",
                }
            }
        ]
        q = alpha_vantage.fetch_quote("AAPL")
        assert (q.price, q.previous_close, q.change, q.change_pct) == (224.2, 225.05, -0.85, -0.38)
        assert (q.day_high, q.day_low, q.volume) == (226.0, 222.1, 52_100_000)
        assert q.as_of == "2026-09-15" and q.source == "Alpha Vantage" and q.company_name == "AAPL"

    def test_quote_missing_price(self, av):
        queues, _ = av
        queues["GLOBAL_QUOTE"] = [{"Global Quote": {}}]
        with pytest.raises(LookupError, match="no quote"):
            alpha_vantage.fetch_quote("AAPL")

    def test_history_compact_and_trimmed(self, av):
        queues, seen = av
        series = {
            f"2026-09-{d:02d}": {
                "1. open": "1",
                "2. high": "2",
                "3. low": "0.5",
                "4. close": str(d),
                "5. volume": "100",
            }
            for d in range(1, 11)
        }
        queues["TIME_SERIES_DAILY"] = [{"Time Series (Daily)": series}]
        h = alpha_vantage.fetch_history("AAPL", "5d")
        assert seen[0].url.params["outputsize"] == "compact"
        assert [b.date for b in h.bars] == [f"2026-09-{d:02d}" for d in range(6, 11)]
        assert h.start_close == 6 and h.end_close == 10 and h.source == "Alpha Vantage"

    def test_history_full_output_for_long_periods(self, av):
        queues, seen = av
        queues["TIME_SERIES_DAILY"] = [
            {
                "Time Series (Daily)": {
                    "2026-01-02": {"1. open": "1", "2. high": "1", "3. low": "1", "4. close": "1", "5. volume": "1"}
                }
            }
        ]
        alpha_vantage.fetch_history("AAPL", "1y")
        assert seen[0].url.params["outputsize"] == "full"

    def test_history_empty(self, av):
        queues, _ = av
        queues["TIME_SERIES_DAILY"] = [{}]
        with pytest.raises(LookupError, match="no history"):
            alpha_vantage.fetch_history("AAPL", "1mo")

    def test_metrics(self, av):
        queues, _ = av
        queues["OVERVIEW"] = [
            {
                "Symbol": "AAPL",
                "RevenueTTM": "385600000000",
                "QuarterlyRevenueGrowthYOY": "0.049",
                "OperatingMarginTTM": "0.312",
                "ProfitMargin": "0.253",
                "EPS": "6.57",
                "ReturnOnEquityTTM": "1.472",
                "PriceToBookRatio": "48.1",
                "PEGRatio": "None",
                "DividendPerShare": "1.00",
                "AnalystTargetPrice": "242",
            }
        ]
        m = alpha_vantage.fetch_metrics("AAPL")
        assert m.total_revenue == 385.6e9 and m.revenue_growth_pct == 4.9
        assert m.operating_margin_pct == 31.2 and m.net_margin_pct == 25.3
        assert m.trailing_eps == 6.57 and m.return_on_equity_pct == 147.2
        assert m.price_to_book == 48.1 and m.peg_ratio is None
        assert m.dividend_rate == 1.0 and m.target_mean_price == 242.0
        assert m.gross_margin_pct is None and m.forward_eps is None and m.source == "Alpha Vantage"

    def test_metrics_empty(self, av):
        queues, _ = av
        queues["OVERVIEW"] = [{}]
        with pytest.raises(LookupError, match="no overview"):
            alpha_vantage.fetch_metrics("AAPL")

    def test_news(self, av):
        queues, seen = av
        queues["NEWS_SENTIMENT"] = [
            {
                "feed": [
                    {
                        "title": "A",
                        "source": "Benzinga",
                        "time_published": "20260914T120000",
                        "url": "u1",
                        "summary": "s",
                    },
                    {"title": ""},
                    {"title": "B"},
                    {"title": "C"},
                ]
            }
        ]
        feed = alpha_vantage.fetch_news("AAPL", 3)
        assert seen[0].url.params["tickers"] == "AAPL" and seen[0].url.params["limit"] == "3"
        assert [a.title for a in feed.articles] == ["A", "B"]
        assert feed.articles[0].publisher == "Benzinga" and feed.articles[0].published == "20260914T120000"

    def test_news_empty(self, av):
        queues, _ = av
        queues["NEWS_SENTIMENT"] = [{"feed": []}]
        with pytest.raises(LookupError, match="no news"):
            alpha_vantage.fetch_news("AAPL", 3)
