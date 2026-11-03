from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

# Never touch real GCP or market APIs from unit tests.
os.environ.setdefault("ANALYST_OFFLINE_MODE", "true")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("HTTP_BACKOFF_BASE_SECONDS", "0")
os.environ.setdefault("HTTP_BACKOFF_MAX_SECONDS", "0")
for var in (
    "ALPHA_VANTAGE_API_KEY",
    "ALPHA_VANTAGE_SECRET",
    "MODEL_ARMOR_TEMPLATE",
    "BQ_USAGE_TABLE",
    "BQ_AUDIT_TABLE",
):
    os.environ.pop(var, None)

from analyst.config import get_settings  # noqa: E402
from analyst.data import secrets  # noqa: E402
from analyst.tools.resilience import clear_all_caches  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    get_settings.cache_clear()
    secrets.get_alpha_vantage_key.cache_clear()
    clear_all_caches()
    yield
    get_settings.cache_clear()
    secrets.get_alpha_vantage_key.cache_clear()
    clear_all_caches()


@pytest.fixture
def online(monkeypatch):
    """Disable offline fixtures so provider adapters are exercised (with mocks)."""
    monkeypatch.setenv("ANALYST_OFFLINE_MODE", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeToolContext:
    def __init__(self):
        self.state: dict = {}


@pytest.fixture
def tool_context():
    return FakeToolContext()


# --------------------------------------------------------------------------- provider fakes (unit tests)


class FakeTicker:
    """Minimal stand-in for ``yfinance.Ticker`` (attributes used by ``analyst.data.yahoo``)."""

    def __init__(self, info=None, fast_info=None, history=None, news=None, dividends=None):
        self.info = info if info is not None else {}
        self.fast_info = fast_info if fast_info is not None else type("FastInfo", (), {})()
        self._history = history
        self.news = news
        self.dividends = dividends
        self.history_calls: list[dict] = []

    def history(self, period, interval, auto_adjust):
        self.history_calls.append({"period": period, "interval": interval, "auto_adjust": auto_adjust})
        if isinstance(self._history, BaseException):
            raise self._history
        return self._history


@pytest.fixture
def fake_yf(monkeypatch):
    """Registry ``{symbol: FakeTicker | Exception | callable}`` served by a patched ``yahoo._ticker``."""
    from analyst.data import yahoo

    registry: dict = {}
    calls: list[str] = []

    def _ticker(symbol):
        calls.append(symbol)
        entry = registry[symbol]
        if isinstance(entry, BaseException):
            raise entry
        if callable(entry) and not isinstance(entry, FakeTicker):
            return entry()
        return entry

    monkeypatch.setattr(yahoo, "_ticker", _ticker)
    registry["__calls__"] = calls
    return registry


@pytest.fixture
def make_ticker():
    return FakeTicker


@pytest.fixture
def mock_http(monkeypatch):
    """Fresh shared httpx client routed through respx; SEC throttle disabled. Yields the respx router."""
    import respx

    from analyst.data import http, sec_edgar

    monkeypatch.setattr(sec_edgar, "_limiter", http.MinIntervalLimiter(0))
    http.set_client(None)
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router
    http.set_client(None)
