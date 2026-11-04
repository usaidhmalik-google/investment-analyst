"""Resilience primitives: exponential backoff with jitter, rate-limit handling, TTL caching, circuit breakers.

The TDD requires 99.9% successful fallback / backoff handling when external financial
APIs rate-limit (HTTP 429) or time out. Every outbound data call in ``analyst.tools``
goes through :func:`call_with_retry`, is memoised with :class:`TTLCache`, and is isolated
per provider with :class:`CircuitBreaker`.
"""

from __future__ import annotations

import functools
import logging
import random
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class DataProviderError(RuntimeError):
    """Raised when an external data provider fails permanently."""


class RateLimitedError(DataProviderError):
    """Raised by provider adapters when a rate limit is signalled (HTTP 429 or equivalent)."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class CircuitBreakerOpenError(DataProviderError):
    """Raised when a call is rejected because the provider circuit breaker is OPEN."""

    def __init__(self, name: str, retry_after: float) -> None:
        super().__init__(f"Circuit breaker '{name}' is OPEN (retry after {retry_after:.1f}s)")
        self.breaker_name = name
        self.retry_after = retry_after


@dataclass
class CircuitBreaker:
    """Thread-safe three-state circuit breaker (CLOSED -> OPEN -> HALF_OPEN)."""

    name: str
    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self._state: str = "CLOSED"
        self._failure_count: int = 0
        self._opened_at: float = 0.0
        self._last_error: str | None = None
        self._total_trips: int = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            self._refresh_state_unlocked()
            return self._state

    def _refresh_state_unlocked(self) -> None:
        if self._state == "OPEN":
            elapsed = self.clock() - self._opened_at
            if elapsed >= self.recovery_timeout:
                self._state = "HALF_OPEN"

    def allow_request(self) -> bool:
        with self._lock:
            self._refresh_state_unlocked()
            return self._state in ("CLOSED", "HALF_OPEN")

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = "CLOSED"
            self._last_error = None

    def record_failure(self, exc: BaseException | None = None) -> None:
        with self._lock:
            self._failure_count += 1
            if exc is not None:
                self._last_error = f"{type(exc).__name__}: {exc}"
            if self._state == "HALF_OPEN" or self._failure_count >= self.failure_threshold:
                if self._state != "OPEN":
                    self._total_trips += 1
                self._state = "OPEN"
                self._opened_at = self.clock()

    def call(self, fn: Callable[[], T]) -> T:
        with self._lock:
            self._refresh_state_unlocked()
            if self._state == "OPEN":
                retry_after = max(0.0, self.recovery_timeout - (self.clock() - self._opened_at))
                raise CircuitBreakerOpenError(self.name, retry_after)
        try:
            result = fn()
        except Exception as exc:
            self.record_failure(exc)
            raise
        self.record_success()
        return result

    def reset(self) -> None:
        with self._lock:
            self._state = "CLOSED"
            self._failure_count = 0
            self._opened_at = 0.0
            self._last_error = None
            self._total_trips = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_state_unlocked()
            return {
                "name": self.name,
                "state": self._state,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_seconds": self.recovery_timeout,
                "total_trips": self._total_trips,
                "last_error": self._last_error,
            }


_BREAKERS: dict[str, CircuitBreaker] = {}
_BREAKERS_LOCK = threading.Lock()


def get_circuit_breaker(
    name: str,
    *,
    failure_threshold: int = 3,
    recovery_timeout: float = 30.0,
) -> CircuitBreaker:
    """Return or create a named ``CircuitBreaker``."""
    with _BREAKERS_LOCK:
        breaker = _BREAKERS.get(name)
        if breaker is None:
            breaker = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
            _BREAKERS[name] = breaker
        return breaker


def circuit_breaker_snapshots() -> dict[str, dict[str, Any]]:
    with _BREAKERS_LOCK:
        items = list(_BREAKERS.items())
    return {name: breaker.snapshot() for name, breaker in items}


def reset_all_circuit_breakers() -> None:
    with _BREAKERS_LOCK:
        breakers = list(_BREAKERS.values())
    for breaker in breakers:
        breaker.reset()


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff policy with full jitter."""

    max_retries: int = 4
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        """Return the sleep before retry ``attempt`` (0-based), honouring Retry-After."""
        if retry_after is not None and retry_after >= 0:
            return min(retry_after, self.max_delay)
        ceiling = min(self.max_delay, self.base_delay * (2**attempt))
        return random.uniform(0, ceiling)  # noqa: S311 - jitter, not crypto


def _parse_retry_after(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def is_retryable(exc: BaseException) -> tuple[bool, float | None]:
    """Classify an exception as retryable and extract any server-provided delay."""
    if isinstance(exc, RateLimitedError):
        return True, exc.retry_after
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code in RETRYABLE_STATUS_CODES, _parse_retry_after(exc.response)
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, ConnectionError)):
        return True, None
    # yfinance raises its own rate-limit exception type; match by name to avoid a hard dependency.
    if type(exc).__name__ in {"YFRateLimitError", "YFTzMissingError"}:
        return True, None
    return False, None


def call_with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy,
    operation: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Invoke ``fn`` retrying transient failures with exponential backoff + jitter."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            retryable, retry_after = is_retryable(exc)
            if not retryable or attempt >= policy.max_retries:
                logger.warning(
                    "external call failed",
                    extra={"operation": operation, "attempt": attempt + 1, "error": repr(exc)},
                )
                raise
            delay = policy.delay_for(attempt, retry_after)
            logger.info(
                "retrying external call",
                extra={"operation": operation, "attempt": attempt + 1, "delay_s": round(delay, 3)},
            )
            sleep(delay)
            attempt += 1


class TTLCache:
    """A small thread-safe LRU cache with per-entry time-to-live."""

    def __init__(self, maxsize: int = 512, ttl: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self.maxsize = maxsize
        self.ttl = ttl
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> tuple[bool, Any]:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return False, None
            expires_at, value = item
            if expires_at < self._clock():
                del self._data[key]
                self.misses += 1
                return False, None
            self._data.move_to_end(key)
            self.hits += 1
            return True, value

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._data[key] = (self._clock() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        return len(self._data)


_ALL_CACHES: list[TTLCache] = []


def cached(ttl_getter: Callable[[], float], maxsize: int = 512) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Memoise a pure data-fetching function. Errors are never cached.

    ``ttl_getter`` is evaluated lazily so tests and settings changes take effect.
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        cache = TTLCache(maxsize=maxsize, ttl=ttl_getter())
        _ALL_CACHES.append(cache)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            cache.ttl = ttl_getter()
            key = (args, tuple(sorted(kwargs.items())))
            hit, value = cache.get(key)
            if hit:
                return value
            value = fn(*args, **kwargs)
            cache.set(key, value)
            return value

        wrapper.cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator


def cache_stats() -> dict[str, Any]:
    """Return aggregate hit/miss/size stats across all registered TTLCaches."""
    total_hits = sum(c.hits for c in _ALL_CACHES)
    total_misses = sum(c.misses for c in _ALL_CACHES)
    total_entries = sum(len(c) for c in _ALL_CACHES)
    total_lookups = total_hits + total_misses
    return {
        "caches_registered": len(_ALL_CACHES),
        "total_entries": total_entries,
        "total_hits": total_hits,
        "total_misses": total_misses,
        "hit_rate": round(total_hits / total_lookups, 4) if total_lookups else 0.0,
    }


def clear_all_caches() -> None:
    """Reset every registered cache and circuit breaker (used by tests)."""
    for cache in _ALL_CACHES:
        cache.clear()
    reset_all_circuit_breakers()
