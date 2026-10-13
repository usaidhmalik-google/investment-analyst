"""Pure technical indicators: known values, edge cases and insufficient-data handling."""

from __future__ import annotations

import pytest

from analyst.strategies import indicators as ind

# StockCharts "RSI" ChartSchool worked example (Wilder smoothing, 14 periods).
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
    46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
    43.42, 42.66, 43.13,
]  # fmt: skip
# Published RSI values starting at the 15th close.
WILDER_RSI = [
    70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46, 41.87,
    45.46, 37.30, 33.08, 37.77,
]  # fmt: skip


class TestSma:
    def test_uses_trailing_window(self):
        assert ind.sma([1, 2, 3, 4, 5], 3) == 4.0
        assert ind.sma([1, 2, 3, 4, 5], 5) == 3.0

    @pytest.mark.parametrize("window", [0, -1, 6])
    def test_invalid_or_insufficient(self, window):
        assert ind.sma([1, 2, 3, 4, 5], window) is None


class TestEma:
    def test_seeded_with_sma(self):
        assert ind.ema_series([1, 2, 3, 4, 5], 3) == pytest.approx([2.0, 3.0, 4.0])

    def test_constant_series(self):
        assert ind.ema_series([7.0] * 10, 4) == pytest.approx([7.0] * 7)

    def test_insufficient(self):
        assert ind.ema_series([1, 2], 3) == []
        assert ind.ema_series([1, 2, 3], 0) == []


class TestRsi:
    def test_all_gains_is_100(self):
        assert ind.rsi(list(range(1, 30)), 14) == 100.0

    def test_all_losses_is_0(self):
        assert ind.rsi(list(range(30, 1, -1)), 14) == pytest.approx(0.0)

    def test_flat_is_50(self):
        assert ind.rsi([10.0] * 20, 14) == 50.0

    def test_insufficient_data(self):
        assert ind.rsi([1.0] * 14, 14) is None
        assert ind.rsi([1.0] * 15, 14) is not None

    @pytest.mark.parametrize("offset", range(len(WILDER_RSI)))
    def test_wilder_textbook_values(self, offset):
        # The published table rounds the seed averages to 2dp (0.24 / 0.10), so allow 0.1 RSI points.
        closes = WILDER_CLOSES[: 15 + offset]
        assert ind.rsi(closes, 14) == pytest.approx(WILDER_RSI[offset], abs=0.1)

    def test_wilder_seed_exact(self):
        # Unrounded seed: avg gain = 3.34 / 14, avg loss = 1.40 / 14 -> RS = 3.34 / 1.40.
        expected = 100 - 100 / (1 + 3.34 / 1.40)
        assert ind.rsi(WILDER_CLOSES[:15], 14) == pytest.approx(expected, abs=1e-9)

    def test_symmetric_alternation_is_50(self):
        closes = [10, 11] * 10 + [10]
        assert ind.rsi(closes, 4) == pytest.approx(50.0, abs=10)


class TestRateOfChange:
    def test_percent_change(self):
        assert ind.rate_of_change([100, 105, 110], 2) == pytest.approx(10.0)
        assert ind.rate_of_change([100, 90], 1) == pytest.approx(-10.0)

    def test_insufficient_or_invalid(self):
        assert ind.rate_of_change([100, 110], 2) is None
        assert ind.rate_of_change([100, 110], 0) is None
        assert ind.rate_of_change([0, 110], 1) is None


class TestMacd:
    def test_aligned_lengths(self):
        values = [100 + i * 0.5 + (i % 3) for i in range(60)]
        line, sig, hist = ind.macd(values)
        assert len(line) == len(sig) == len(hist) == 60 - 33
        assert hist == pytest.approx([m - s for m, s in zip(line, sig, strict=True)])

    def test_macd_line_matches_ema_difference(self):
        values = [float(v) for v in range(1, 61)]
        line, _, _ = ind.macd(values)
        fast = ind.ema_series(values, 12)
        slow = ind.ema_series(values, 26)
        assert line[-1] == pytest.approx(fast[-1] - slow[-1])

    def test_uptrend_has_positive_line(self):
        line, _, _ = ind.macd([float(v) for v in range(1, 61)])
        assert all(v > 0 for v in line)

    def test_too_short_for_slow_ema(self):
        assert ind.macd([1.0] * 25) == ([], [], [])

    def test_too_short_for_signal_line(self):
        line, sig, hist = ind.macd([float(v) for v in range(30)])
        assert len(line) == 5 and sig == [] and hist == []


class TestBollinger:
    def test_constant_series_collapses(self):
        assert ind.bollinger([5.0] * 20) == (5.0, 5.0, 5.0)

    def test_population_std(self):
        lower, mid, upper = ind.bollinger([1, 2, 3, 4, 5], window=5, num_std=2)
        std = (2.0) ** 0.5  # population variance of 1..5 is 2
        assert mid == 3.0
        assert lower == pytest.approx(3 - 2 * std)
        assert upper == pytest.approx(3 + 2 * std)

    def test_insufficient(self):
        assert ind.bollinger([1.0] * 19, 20) is None


class TestPercentB:
    def test_positions(self):
        bands = (90.0, 100.0, 110.0)
        assert ind.percent_b(90, bands) == 0.0
        assert ind.percent_b(100, bands) == 0.5
        assert ind.percent_b(110, bands) == 1.0
        assert ind.percent_b(115, bands) == pytest.approx(1.25)

    def test_degenerate_bands(self):
        assert ind.percent_b(5.0, (5.0, 5.0, 5.0)) is None


class TestAtr:
    def test_wilder_smoothing(self):
        highs = [10, 12, 13, 12, 15]
        lows = [8, 9, 11, 10, 11]
        closes = [9, 11, 12, 11, 14]
        # TR[1..4] = max(H-L, |H-Cprev|, |L-Cprev|) = 3, 2, 2, 4
        # window 3: seed=(3+2+2)/3=7/3; then (7/3*2+4)/3
        expected = (7 / 3 * 2 + 4) / 3
        assert ind.atr(highs, lows, closes, 3) == pytest.approx(expected)

    def test_gap_uses_previous_close(self):
        # Gap up: H-L = 1 but |H - prev close| = 11
        assert ind.atr([10, 21], [9, 20], [10, 20.5], 1) == pytest.approx(11.0)

    def test_insufficient_or_mismatched(self):
        assert ind.atr([1, 2], [1, 2], [1, 2], 2) is None
        assert ind.atr([1, 2, 3], [1, 2], [1, 2, 3], 1) is None


class TestCagr:
    def test_doubling_over_one_year(self):
        assert ind.cagr(100, 200, 1) == pytest.approx(100.0)

    def test_five_year(self):
        assert ind.cagr(1.0, 1.05**5, 5) == pytest.approx(5.0)

    @pytest.mark.parametrize("args", [(0, 1, 1), (1, 0, 1), (1, 1, 0), (-1, 2, 3)])
    def test_invalid(self, args):
        assert ind.cagr(*args) is None
