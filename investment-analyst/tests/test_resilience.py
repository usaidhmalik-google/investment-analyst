"""Backoff, retry classification and TTL caching primitives."""

from __future__ import annotations

import httpx
import pytest

from analyst.tools import resilience
from analyst.tools.resilience import (
    DataProviderError,
    RateLimitedError,
    RetryPolicy,
    TTLCache,
    cached,
    call_with_retry,
    clear_all_caches,
    is_retryable,
)


def _status_error(code: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/x")
    response = httpx.Response(code, headers=headers or {}, request=request)
    return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


# --------------------------------------------------------------------------- RetryPolicy


class TestRetryPolicy:
    def test_jitter_within_exponential_ceiling(self):
        policy = RetryPolicy(max_retries=5, base_delay=0.5, max_delay=8.0)
        for attempt, ceiling in [(0, 0.5), (1, 1.0), (2, 2.0), (3, 4.0), (4, 8.0)]:
            delays = [policy.delay_for(attempt) for _ in range(200)]
            assert all(0 <= d <= ceiling for d in delays), (attempt, max(delays))

    def test_ceiling_capped_at_max_delay(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=3.0)
        assert all(policy.delay_for(10) <= 3.0 for _ in range(200))

    def test_uses_full_jitter(self, monkeypatch):
        seen = {}

        def fake_uniform(lo, hi):
            seen["args"] = (lo, hi)
            return hi

        monkeypatch.setattr(resilience.random, "uniform", fake_uniform)
        assert RetryPolicy(base_delay=0.5, max_delay=8.0).delay_for(3) == 4.0
        assert seen["args"] == (0, 4.0)

    def test_retry_after_honoured(self):
        policy = RetryPolicy(base_delay=0.5, max_delay=8.0)
        assert policy.delay_for(0, retry_after=2.5) == 2.5
        assert policy.delay_for(5, retry_after=0) == 0

    def test_retry_after_capped(self):
        assert RetryPolicy(max_delay=8.0).delay_for(0, retry_after=120) == 8.0

    def test_negative_retry_after_falls_back_to_backoff(self):
        policy = RetryPolicy(base_delay=0.5, max_delay=8.0)
        assert 0 <= policy.delay_for(0, retry_after=-1) <= 0.5


# --------------------------------------------------------------------------- classification


class TestIsRetryable:
    @pytest.mark.parametrize("code", [408, 425, 429, 500, 502, 503, 504])
    def test_retryable_status_codes(self, code):
        assert is_retryable(_status_error(code)) == (True, None)

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_non_retryable_status_codes(self, code):
        assert is_retryable(_status_error(code)) == (False, None)

    def test_retry_after_header_parsed(self):
        assert is_retryable(_status_error(429, {"Retry-After": "3"})) == (True, 3.0)

    def test_http_date_retry_after_ignored(self):
        exc = _status_error(503, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
        assert is_retryable(exc) == (True, None)

    def test_rate_limited_error(self):
        assert is_retryable(RateLimitedError("slow down", retry_after=7)) == (True, 7)
        assert is_retryable(RateLimitedError("slow down")) == (True, None)

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("timeout"),
            httpx.ConnectTimeout("timeout"),
            httpx.ConnectError("refused"),
            TimeoutError(),
            ConnectionError(),
        ],
    )
    def test_transient_network_errors(self, exc):
        assert is_retryable(exc) == (True, None)

    def test_yfinance_rate_limit_matched_by_name(self):
        YFRateLimitError = type("YFRateLimitError", (Exception,), {})
        YFTzMissingError = type("YFTzMissingError", (Exception,), {})
        assert is_retryable(YFRateLimitError("Too Many Requests")) == (True, None)
        assert is_retryable(YFTzMissingError("tz")) == (True, None)

    @pytest.mark.parametrize("exc", [ValueError("bad"), LookupError("none"), DataProviderError("perm"), KeyError("k")])
    def test_permanent_errors(self, exc):
        assert is_retryable(exc) == (False, None)

    def test_parse_retry_after_none_response(self):
        assert resilience._parse_retry_after(None) is None


# --------------------------------------------------------------------------- call_with_retry


class Flaky:
    def __init__(self, failures: list[BaseException], result: str = "ok"):
        self.failures = list(failures)
        self.calls = 0
        self.result = result

    def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.result


class TestCallWithRetry:
    def test_success_first_try_no_sleep(self):
        sleeps: list[float] = []
        fn = Flaky([])
        assert call_with_retry(fn, policy=RetryPolicy(), operation="op", sleep=sleeps.append) == "ok"
        assert fn.calls == 1 and sleeps == []

    def test_success_after_retries(self):
        sleeps: list[float] = []
        fn = Flaky([_status_error(429), httpx.ReadTimeout("t"), _status_error(503)])
        policy = RetryPolicy(max_retries=4, base_delay=0.5, max_delay=8.0)
        assert call_with_retry(fn, policy=policy, operation="op", sleep=sleeps.append) == "ok"
        assert fn.calls == 4
        assert len(sleeps) == 3
        assert sleeps[0] <= 0.5 and sleeps[1] <= 1.0 and sleeps[2] <= 2.0

    def test_retry_after_used_as_sleep(self):
        sleeps: list[float] = []
        fn = Flaky([_status_error(429, {"Retry-After": "2"}), RateLimitedError("x", retry_after=1.5)])
        call_with_retry(fn, policy=RetryPolicy(max_delay=8.0), operation="op", sleep=sleeps.append)
        assert sleeps == [2.0, 1.5]

    def test_gives_up_after_max_retries(self):
        sleeps: list[float] = []
        fn = Flaky([_status_error(503)] * 10)
        with pytest.raises(httpx.HTTPStatusError):
            call_with_retry(fn, policy=RetryPolicy(max_retries=3), operation="op", sleep=sleeps.append)
        assert fn.calls == 4  # initial + 3 retries
        assert len(sleeps) == 3

    def test_zero_retries(self):
        fn = Flaky([_status_error(503)])
        with pytest.raises(httpx.HTTPStatusError):
            call_with_retry(fn, policy=RetryPolicy(max_retries=0), operation="op", sleep=lambda _: None)
        assert fn.calls == 1

    def test_non_retryable_raises_immediately(self):
        sleeps: list[float] = []
        fn = Flaky([_status_error(404)])
        with pytest.raises(httpx.HTTPStatusError):
            call_with_retry(fn, policy=RetryPolicy(max_retries=5), operation="op", sleep=sleeps.append)
        assert fn.calls == 1 and sleeps == []

    def test_value_error_not_retried(self):
        fn = Flaky([ValueError("bad ticker")])
        with pytest.raises(ValueError, match="bad ticker"):
            call_with_retry(fn, policy=RetryPolicy(), operation="op", sleep=lambda _: None)
        assert fn.calls == 1


# --------------------------------------------------------------------------- TTLCache


class TestTTLCache:
    def test_hit_and_miss_counters(self):
        cache = TTLCache(ttl=10, clock=FakeClock())
        assert cache.get("a") == (False, None)
        cache.set("a", 1)
        assert cache.get("a") == (True, 1)
        assert cache.hits == 1 and cache.misses == 1
        assert len(cache) == 1

    def test_expiry(self):
        clock = FakeClock()
        cache = TTLCache(ttl=10, clock=clock)
        cache.set("a", 1)
        clock.now += 10  # exactly at expiry is still valid
        assert cache.get("a") == (True, 1)
        clock.now += 0.001
        assert cache.get("a") == (False, None)
        assert len(cache) == 0

    def test_lru_eviction(self):
        cache = TTLCache(maxsize=2, ttl=100, clock=FakeClock())
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("a")  # a becomes most recently used
        cache.set("c", 3)
        assert cache.get("b") == (False, None)
        assert cache.get("a") == (True, 1)
        assert cache.get("c") == (True, 3)

    def test_overwrite_refreshes_ttl(self):
        clock = FakeClock()
        cache = TTLCache(ttl=10, clock=clock)
        cache.set("a", 1)
        clock.now += 8
        cache.set("a", 2)
        clock.now += 8
        assert cache.get("a") == (True, 2)

    def test_clear(self):
        cache = TTLCache(clock=FakeClock())
        cache.set("a", 1)
        cache.get("a")
        cache.clear()
        assert len(cache) == 0 and cache.hits == 0 and cache.misses == 0


class TestCachedDecorator:
    def test_memoises_by_args_and_kwargs(self):
        calls = []

        @cached(lambda: 60)
        def fetch(x, y=0):
            calls.append((x, y))
            return x + y

        assert fetch(1, y=2) == 3
        assert fetch(1, y=2) == 3
        assert fetch(1, y=3) == 4
        assert calls == [(1, 2), (1, 3)]
        assert fetch.cache.hits == 1

    def test_exceptions_not_cached(self):
        calls = []

        @cached(lambda: 60)
        def fetch(x):
            calls.append(x)
            if len(calls) == 1:
                raise RuntimeError("transient")
            return x * 2

        with pytest.raises(RuntimeError):
            fetch(5)
        assert fetch(5) == 10
        assert fetch(5) == 10
        assert calls == [5, 5]

    def test_ttl_getter_is_lazy(self):
        ttl = {"value": 60.0}

        @cached(lambda: ttl["value"])
        def fetch():
            return 1

        ttl["value"] = 5.0
        fetch()
        assert fetch.cache.ttl == 5.0

    def test_clear_all_caches(self):
        calls = []

        @cached(lambda: 60)
        def fetch():
            calls.append(1)
            return len(calls)

        assert fetch() == 1
        assert fetch() == 1
        clear_all_caches()
        assert fetch() == 2
