"""Shared HTTP client helpers with timeouts, retries and polite rate limiting."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from ..config import get_settings
from ..tools.resilience import RetryPolicy, call_with_retry


def retry_policy() -> RetryPolicy:
    s = get_settings()
    return RetryPolicy(
        max_retries=s.http_max_retries,
        base_delay=s.http_backoff_base_seconds,
        max_delay=s.http_backoff_max_seconds,
    )


class MinIntervalLimiter:
    """Client-side throttle guaranteeing a minimum gap between requests (e.g. SEC 10 req/s)."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = self._last + self.min_interval - now
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()


_client: httpx.Client | None = None
_client_lock = threading.Lock()


def get_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                timeout=get_settings().http_timeout_seconds,
                follow_redirects=True,
                headers={"Accept-Encoding": "gzip, deflate"},
            )
        return _client


def set_client(client: httpx.Client | None) -> None:
    """Override the shared client (tests inject a mock transport)."""
    global _client
    with _client_lock:
        _client = client


def get_once(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    limiter: MinIntervalLimiter | None = None,
) -> httpx.Response:
    """Single GET attempt; raises ``httpx.HTTPStatusError`` for non-2xx responses."""
    if limiter is not None:
        limiter.wait()
    response = get_client().get(url, params=params, headers=headers)
    response.raise_for_status()
    return response


def get(
    url: str,
    *,
    operation: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    limiter: MinIntervalLimiter | None = None,
) -> httpx.Response:
    """GET with retry on 429/5xx/timeouts. Raises ``httpx.HTTPStatusError`` on final failure."""
    return call_with_retry(
        lambda: get_once(url, params=params, headers=headers, limiter=limiter),
        policy=retry_policy(),
        operation=operation,
    )
