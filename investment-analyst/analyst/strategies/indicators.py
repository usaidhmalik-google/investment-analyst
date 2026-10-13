"""Pure, deterministic technical indicators (no I/O, no LLM). Fully unit-tested."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise


def sma(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def ema_series(values: Sequence[float], window: int) -> list[float]:
    """Exponential moving average seeded with the SMA of the first ``window`` values."""
    if window <= 0 or len(values) < window:
        return []
    k = 2 / (window + 1)
    seed = sum(values[:window]) / window
    out = [seed]
    for v in values[window:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values: Sequence[float], window: int = 14) -> float | None:
    """Wilder's Relative Strength Index."""
    if len(values) < window + 1:
        return None
    gains, losses = [], []
    for prev, cur in pairwise(values):
        delta = cur - prev
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    for g, l in zip(gains[window:], losses[window:], strict=True):  # noqa: E741
        avg_gain = (avg_gain * (window - 1) + g) / window
        avg_loss = (avg_loss * (window - 1) + l) / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def rate_of_change(values: Sequence[float], periods: int) -> float | None:
    """Percent change over ``periods`` bars."""
    if periods <= 0 or len(values) <= periods or values[-periods - 1] == 0:
        return None
    return (values[-1] / values[-periods - 1] - 1) * 100


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float], list[float]]:
    """Return aligned ``(macd_line, signal_line, histogram)`` series (may be empty)."""
    fast_ema = ema_series(values, fast)
    slow_ema = ema_series(values, slow)
    if not slow_ema:
        return [], [], []
    offset = slow - fast
    line = [f - s for f, s in zip(fast_ema[offset:], slow_ema, strict=True)]
    sig = ema_series(line, signal)
    if not sig:
        return line, [], []
    aligned_line = line[signal - 1 :]
    hist = [m - s for m, s in zip(aligned_line, sig, strict=True)]
    return aligned_line, sig, hist


def bollinger(values: Sequence[float], window: int = 20, num_std: float = 2.0) -> tuple[float, float, float] | None:
    """Return ``(lower, middle, upper)`` bands using population standard deviation."""
    if len(values) < window:
        return None
    recent = values[-window:]
    mid = sum(recent) / window
    var = sum((v - mid) ** 2 for v in recent) / window
    std = var**0.5
    return mid - num_std * std, mid, mid + num_std * std


def percent_b(price: float, bands: tuple[float, float, float]) -> float | None:
    lower, _, upper = bands
    if upper == lower:
        return None
    return (price - lower) / (upper - lower)


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int = 14) -> float | None:
    """Wilder's Average True Range."""
    n = len(closes)
    if n < window + 1 or len(highs) != n or len(lows) != n:
        return None
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, n)]
    value = sum(trs[:window]) / window
    for tr in trs[window:]:
        value = (value * (window - 1) + tr) / window
    return value


def cagr(start: float, end: float, years: float) -> float | None:
    """Compound annual growth rate in percent."""
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100
