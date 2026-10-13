"""Deterministic strategy signals: every signal branch, threshold boundary and INSUFFICIENT_DATA path.

Two complementary styles are used:
  * realistic synthetic price series whose indicator values are asserted first, so the expected
    signal follows unambiguously from the documented thresholds; and
  * table-driven tests that pin indicator values (monkeypatching ``engine.ind``) to probe every
    boundary of the scoring rules exactly.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from analyst.data.schemas import FinancialMetrics, PriceBar, Quote
from analyst.strategies import engine
from analyst.strategies.engine import INSUFFICIENT, evaluate_income, evaluate_momentum, evaluate_swing, evaluate_value

AS_OF = "2026-09-15T20:00:00+00:00"


def make_bars(closes: list[float], spread: float = 0.01) -> list[PriceBar]:
    start = date(2025, 1, 1)
    return [
        PriceBar(
            date=(start + timedelta(days=i)).isoformat(),
            open=c,
            high=c * (1 + spread),
            low=c * (1 - spread),
            close=c,
            volume=1_000,
        )
        for i, c in enumerate(closes)
    ]


def make_quote(**kw) -> Quote:
    base = {"ticker": "TEST", "company_name": "Test Corp", "price": 100.0, "source": "test", "as_of": AS_OF}
    return Quote(**{**base, **kw})


def make_metrics(**kw) -> FinancialMetrics:
    return FinancialMetrics(**{"ticker": "TEST", "source": "test", "as_of": AS_OF, **kw})


# =========================================================================== momentum


def zigzag_uptrend(n: int = 260) -> list[float]:
    closes = [100.0]
    for i in range(n - 1):
        closes.append(closes[-1] + (2 if i % 2 == 0 else -1))
    return closes


class TestMomentumSynthetic:
    def test_bullish_full_score(self):
        s = evaluate_momentum("TEST", make_bars(zigzag_uptrend()), AS_OF)
        ind = s.indicators
        assert ind["price"] > ind["sma_50"] > ind["sma_200"]
        assert 50 <= ind["rsi_14"] <= 70
        assert ind["roc_3m_pct"] > 0 and ind["roc_6m_pct"] > 0
        assert ind["golden_cross"] is True
        assert (s.signal, s.score, s.max_score) == ("BULLISH", 6, 6)
        assert s.strategy == "momentum" and s.ticker == "TEST" and s.as_of == AS_OF
        assert "RSI(14) is between 50 and 70: positive momentum without being overbought (+1)." in s.rationale
        assert s.rationale[-1] == "Thresholds: score >= 5 BULLISH, <= 2 BEARISH, otherwise NEUTRAL."

    def test_bullish_but_overbought(self):
        s = evaluate_momentum("TEST", make_bars([100.0 + i for i in range(260)]), AS_OF)
        assert s.indicators["rsi_14"] == 100.0
        assert (s.signal, s.score) == ("BULLISH", 5)
        assert "RSI(14) is above 70: overbought, momentum may be stretched (0)." in s.rationale

    def test_bearish_downtrend(self):
        s = evaluate_momentum("TEST", make_bars([400.0 - i for i in range(260)]), AS_OF)
        ind = s.indicators
        assert ind["price"] < ind["sma_50"] < ind["sma_200"]
        assert ind["rsi_14"] < 50 and ind["roc_3m_pct"] < 0 and ind["roc_6m_pct"] < 0
        assert (s.signal, s.score) == ("BEARISH", 0)
        assert s.rationale[:6] == [
            "Price is below its 50-day SMA (0).",
            "Price is below its 200-day SMA (0).",
            "50-day SMA is below the 200-day SMA (death-cross regime, 0).",
            "RSI(14) is below 50: weak momentum (0).",
            "3-month rate of change is negative (0).",
            "6-month rate of change is negative or unavailable (0).",
        ]

    def test_neutral_pullback_in_uptrend(self):
        up = [100 + i * 100 / 169 for i in range(170)]
        closes = up + [up[-1] - 0.5 * (j + 1) for j in range(30)]
        s = evaluate_momentum("TEST", make_bars(closes), AS_OF)
        ind = s.indicators
        assert ind["sma_200"] < ind["price"] < ind["sma_50"]
        assert ind["golden_cross"] is True and ind["rsi_14"] < 50
        assert ind["roc_3m_pct"] > 0 and ind["roc_6m_pct"] > 0
        assert (s.signal, s.score) == ("NEUTRAL", 4)

    @pytest.mark.parametrize("n", [0, 1, 50, 199])
    def test_insufficient_history(self, n):
        s = evaluate_momentum("TEST", make_bars([100.0 + i for i in range(n)]), AS_OF)
        assert s.signal == INSUFFICIENT and s.score == 0 and s.max_score == 6
        assert s.rationale == ["Momentum needs at least 200 daily bars."]

    def test_exactly_200_bars_is_enough(self):
        s = evaluate_momentum("TEST", make_bars([100.0 + i for i in range(200)]), AS_OF)
        assert s.signal != INSUFFICIENT


def _pin_momentum(monkeypatch, *, sma50, sma200, rsi, roc63, roc126):
    monkeypatch.setattr(engine.ind, "sma", lambda values, window: {50: sma50, 200: sma200}[window])
    monkeypatch.setattr(engine.ind, "rsi", lambda values, window=14: rsi)
    monkeypatch.setattr(engine.ind, "rate_of_change", lambda values, periods: {63: roc63, 126: roc126}[periods])


class TestMomentumThresholds:
    PRICE = 100.0

    @pytest.mark.parametrize(
        ("sma50", "sma200", "rsi", "roc63", "roc126", "score", "signal"),
        [
            (90, 80, 60, 5, 5, 6, "BULLISH"),
            (90, 80, 75, 5, 5, 5, "BULLISH"),  # boundary: 5 -> BULLISH
            (90, 80, 40, 5, 5, 5, "BULLISH"),
            (90, 80, 40, -5, 5, 4, "NEUTRAL"),
            (90, 80, 40, -5, -5, 3, "NEUTRAL"),  # boundary: 3 -> NEUTRAL
            (110, 80, 40, -5, -5, 2, "BEARISH"),  # boundary: 2 -> BEARISH (price>200, golden)
            (110, 120, 60, -5, -5, 1, "BEARISH"),
            (110, 120, 40, -5, None, 0, "BEARISH"),  # roc126 unavailable counts as 0
            (100, 100, 50, 0, 0, 1, "BEARISH"),  # equality is never "above"; RSI 50 is inclusive
            (99.99, 99.98, 70, 0.01, 0.01, 6, "BULLISH"),  # RSI 70 inclusive
            (99.99, 99.98, 70.01, 0.01, 0.01, 5, "BULLISH"),
            (99.99, 99.98, 49.99, 0.01, 0.01, 5, "BULLISH"),
            (101, 99.98, 49.99, 0.01, 0.01, 4, "NEUTRAL"),
        ],
    )
    def test_scoring_table(self, monkeypatch, sma50, sma200, rsi, roc63, roc126, score, signal):
        _pin_momentum(monkeypatch, sma50=sma50, sma200=sma200, rsi=rsi, roc63=roc63, roc126=roc126)
        s = evaluate_momentum("TEST", make_bars([self.PRICE]), AS_OF)
        assert (s.score, s.signal) == (score, signal)
        assert len(s.rationale) == 7
        assert s.indicators["golden_cross"] is (sma50 > sma200)

    @pytest.mark.parametrize("missing", ["sma50", "sma200", "rsi", "roc63"])
    def test_any_core_indicator_missing_is_insufficient(self, monkeypatch, missing):
        values = {"sma50": 90, "sma200": 80, "rsi": 60, "roc63": 5, "roc126": 5}
        values[missing] = None
        _pin_momentum(monkeypatch, **values)
        s = evaluate_momentum("TEST", make_bars([self.PRICE]), AS_OF)
        assert s.signal == INSUFFICIENT
        assert "golden_cross" not in s.indicators

    def test_roc126_missing_alone_is_not_insufficient(self, monkeypatch):
        _pin_momentum(monkeypatch, sma50=90, sma200=80, rsi=60, roc63=5, roc126=None)
        s = evaluate_momentum("TEST", make_bars([self.PRICE]), AS_OF)
        assert (s.signal, s.score) == ("BULLISH", 5)
        assert s.indicators["roc_6m_pct"] is None

    def test_indicators_rounded_to_two_dp(self, monkeypatch):
        _pin_momentum(monkeypatch, sma50=90.123456, sma200=80.98765, rsi=60.55555, roc63=5.4321, roc126=1.23456)
        s = evaluate_momentum("TEST", make_bars([100.004]), AS_OF)
        assert s.indicators == {
            "price": 100.0,
            "sma_50": 90.12,
            "sma_200": 80.99,
            "rsi_14": 60.56,
            "roc_3m_pct": 5.43,
            "roc_6m_pct": 1.23,
            "golden_cross": True,
        }


# =========================================================================== value


class TestValue:
    def test_undervalued_full_score(self):
        q = make_quote(trailing_pe=12.0, forward_pe=10.0, market_cap=100e9)
        m = make_metrics(price_to_book=1.5, peg_ratio=0.8, free_cash_flow=8e9, debt_to_equity=0.4)
        s = evaluate_value("TEST", q, m, AS_OF)
        assert (s.signal, s.score, s.max_score) == ("UNDERVALUED", 6, 6)
        assert s.indicators == {
            "trailing_pe": 12.0,
            "forward_pe": 10.0,
            "price_to_book": 1.5,
            "peg_ratio": 0.8,
            "fcf_yield_pct": 8.0,
            "debt_to_equity": 0.4,
        }
        assert s.rationale == [
            "Trailing P/E is below 15 (+1).",
            "Forward P/E is below trailing P/E, implying expected earnings growth (+1).",
            "Price-to-book is below 3 (+1).",
            "PEG ratio is below 1 (+1).",
            "Free-cash-flow yield is above 5% (+1).",
            "Debt-to-equity is below 1.0x (+1).",
            "Thresholds: score >= 3 UNDERVALUED, <= 0 OVERVALUED, otherwise FAIRLY_VALUED.",
        ]

    def test_overvalued_minimum_score(self):
        q = make_quote(trailing_pe=60.0, forward_pe=70.0, market_cap=1e12)
        m = make_metrics(price_to_book=20.0, peg_ratio=3.0, free_cash_flow=5e9, debt_to_equity=2.0)
        s = evaluate_value("TEST", q, m, AS_OF)
        assert s.indicators["fcf_yield_pct"] == 0.5
        assert (s.signal, s.score) == ("OVERVALUED", -3)
        assert "Trailing P/E is above 30 (-1)." in s.rationale
        assert "PEG ratio is above 2 (-1)." in s.rationale
        assert "Free-cash-flow yield is below 2% (-1)." in s.rationale
        assert "Price-to-book is 3 or higher (0)." in s.rationale
        assert "Debt-to-equity is 1.0x or higher (0)." in s.rationale
        assert not any("Forward P/E" in r for r in s.rationale)

    def test_fairly_valued_middle_band(self):
        # P/E 20 (0), fwd 18 < 20 (+1), P/B 5 (0), PEG 1.5 (0), FCF 3% (0), D/E 0.5 (+1) -> 2
        q = make_quote(trailing_pe=20.0, forward_pe=18.0, market_cap=100e9)
        m = make_metrics(price_to_book=5.0, peg_ratio=1.5, free_cash_flow=3e9, debt_to_equity=0.5)
        s = evaluate_value("TEST", q, m, AS_OF)
        assert (s.signal, s.score) == ("FAIRLY_VALUED", 2)
        assert "Trailing P/E is between 15 and 30 (0)." in s.rationale
        assert "PEG ratio is between 1 and 2 (0)." in s.rationale
        assert "Free-cash-flow yield is between 2% and 5% (0)." in s.rationale

    @pytest.mark.parametrize(
        ("pe", "fwd", "pb", "peg", "fcf", "de", "score", "signal"),
        [
            (14.99, None, 2.99, None, None, 0.99, 3, "UNDERVALUED"),  # boundary 3
            (15.0, None, 3.0, 1.0, None, 1.0, 0, "OVERVALUED"),  # every inclusive bound scores 0
            (30.0, None, 3.0, 2.0, None, 1.0, 0, "OVERVALUED"),
            (30.01, None, 2.0, 2.0, None, 0.5, 1, "FAIRLY_VALUED"),  # boundary 1
            (20.0, 19.0, 4.0, 2.01, None, 0.5, 1, "FAIRLY_VALUED"),
            (20.0, 20.0, 4.0, 1.5, None, 0.5, 1, "FAIRLY_VALUED"),  # equal forward P/E: no bonus
        ],
    )
    def test_threshold_table(self, pe, fwd, pb, peg, fcf, de, score, signal):
        q = make_quote(trailing_pe=pe, forward_pe=fwd, market_cap=None)
        m = make_metrics(price_to_book=pb, peg_ratio=peg, free_cash_flow=fcf, debt_to_equity=de)
        s = evaluate_value("TEST", q, m, AS_OF)
        assert (s.score, s.signal) == (score, signal)

    @pytest.mark.parametrize(("fcf", "expected_delta"), [(5.01e9, 1), (5e9, 0), (2e9, 0), (1.99e9, -1)])
    def test_fcf_yield_boundaries(self, fcf, expected_delta):
        q = make_quote(trailing_pe=20.0, market_cap=100e9)
        m = make_metrics(price_to_book=5.0, peg_ratio=1.5, free_cash_flow=fcf)
        assert evaluate_value("TEST", q, m, AS_OF).score == expected_delta

    def test_negative_fcf_penalised(self):
        q = make_quote(trailing_pe=20.0, market_cap=100e9)
        m = make_metrics(price_to_book=5.0, peg_ratio=1.5, free_cash_flow=-1e9)
        s = evaluate_value("TEST", q, m, AS_OF)
        assert s.indicators["fcf_yield_pct"] == -1.0 and s.score == -1

    def test_non_positive_multiples_are_not_meaningful(self):
        q = make_quote(trailing_pe=-12.0, forward_pe=25.0, market_cap=None)
        m = make_metrics(price_to_book=-4.0, peg_ratio=-0.5, debt_to_equity=-2.5)
        s = evaluate_value("TEST", q, m, AS_OF)
        assert s.score == 0 and s.signal == "OVERVALUED"
        assert s.rationale[:4] == [
            "Trailing P/E is not meaningful (zero or negative earnings) (0).",
            "Price-to-book is not meaningful (zero or negative book value) (0).",
            "PEG ratio is not meaningful (zero or negative growth/earnings) (0).",
            "Debt-to-equity is negative (negative shareholders' equity) (0).",
        ]

    def test_zero_market_cap_skips_fcf_yield(self):
        q = make_quote(trailing_pe=12.0, forward_pe=10.0, market_cap=0)
        m = make_metrics(price_to_book=1.0, free_cash_flow=1e9)
        s = evaluate_value("TEST", q, m, AS_OF)
        assert s.indicators["fcf_yield_pct"] is None
        assert s.score == 3

    def test_insufficient_with_two_inputs(self):
        q = make_quote(trailing_pe=12.0, market_cap=None)
        m = make_metrics(price_to_book=1.0, free_cash_flow=1e9)  # FCF without market cap is unusable
        s = evaluate_value("TEST", q, m, AS_OF)
        assert s.signal == INSUFFICIENT and s.score == 0
        assert s.rationale == ["Value needs at least three valuation inputs."]

    def test_exactly_three_inputs_is_enough(self):
        q = make_quote(forward_pe=10.0, market_cap=None)
        m = make_metrics(peg_ratio=0.5, debt_to_equity=0.5)
        s = evaluate_value("TEST", q, m, AS_OF)
        # No trailing P/E -> no forward-P/E bonus; PEG +1, D/E +1.
        assert (s.signal, s.score) == ("FAIRLY_VALUED", 2)

    def test_offline_fixture_nvda_is_overvalued(self):
        from analyst.data import fixtures

        s = evaluate_value("NVDA", fixtures.quote("NVDA"), fixtures.metrics("NVDA"), AS_OF)
        # P/E 48.2 (-1), fwd 32.5 < 48.2 (+1), P/B 52.3 (0), PEG 1.12 (0), FCF 0.86% (-1), D/E 0.42 (+1)
        assert s.indicators["fcf_yield_pct"] == 0.86
        assert (s.score, s.signal) == (0, "OVERVALUED")


# =========================================================================== swing


def flat(n: int = 20, level: float = 100.0) -> list[float]:
    return [level] * n


class TestSwingSynthetic:
    def test_buy_setup_decelerating_selloff(self):
        dec = [100 - 2 * (i + 1) for i in range(20)]
        closes = flat() + dec + [dec[-1] - 0.2 * (i + 1) for i in range(5)]
        s = evaluate_swing("TEST", make_bars(closes), AS_OF)
        ind = s.indicators
        assert ind["rsi_14"] < 35 and ind["macd_histogram_rising"] is True
        assert (s.signal, s.score, s.max_score) == ("BUY_SETUP", 3, 3)
        assert s.rationale[0].startswith("Price is near the lower Bollinger band")

    def test_sell_setup_decelerating_rally(self):
        inc = [100 + 2 * (i + 1) for i in range(20)]
        closes = flat() + inc + [inc[-1] + 0.2 * (i + 1) for i in range(5)]
        s = evaluate_swing("TEST", make_bars(closes), AS_OF)
        ind = s.indicators
        assert ind["rsi_14"] > 65 and ind["macd_histogram_rising"] is False
        assert (s.signal, s.score) == ("SELL_SETUP", 3)
        assert s.rationale[0].startswith("Price is near the upper Bollinger band")

    def test_no_setup_when_selloff_accelerating(self):
        slow = [100 - 0.2 * (i + 1) for i in range(20)]
        closes = flat() + slow + [slow[-1] - 2 * (i + 1) for i in range(5)]
        s = evaluate_swing("TEST", make_bars(closes), AS_OF)
        assert s.indicators["percent_b"] < 0.2 and s.indicators["macd_histogram_rising"] is False
        assert (s.signal, s.score) == ("NO_SETUP", 1)

    def test_no_setup_flat_market(self):
        s = evaluate_swing("TEST", make_bars(flat(40)), AS_OF)
        ind = s.indicators
        assert ind["percent_b"] is None and ind["rsi_14"] == 50.0 and ind["macd_histogram"] == 0.0
        assert (s.signal, s.score) == ("NO_SETUP", 0)
        assert ind["support_20d"] == 99.0 and ind["resistance_20d"] == 101.0
        assert ind["atr_14"] == 2.0 and ind["atr_pct_of_price"] == 2.0
        assert s.rationale[0] == "No confluence between band position/RSI extremes and MACD histogram direction."

    def test_minimum_bars(self):
        closes = [100 + (i % 5) for i in range(35)]
        assert evaluate_swing("TEST", make_bars(closes), AS_OF).signal != INSUFFICIENT
        short = evaluate_swing("TEST", make_bars(closes[:34]), AS_OF)
        assert short.signal == INSUFFICIENT and short.score == 0 and short.max_score == 3
        assert short.indicators == {"price": 103.0}
        assert short.rationale == ["Swing needs at least 35 daily bars."]

    def test_empty_bars(self):
        s = evaluate_swing("TEST", [], AS_OF)
        assert s.signal == INSUFFICIENT and s.indicators == {"price": None}


def _pin_swing(monkeypatch, *, bands, rsi, hist, atr=1.0):
    monkeypatch.setattr(engine.ind, "bollinger", lambda values, window, num_std: bands)
    monkeypatch.setattr(engine.ind, "rsi", lambda values, window=14: rsi)
    monkeypatch.setattr(engine.ind, "macd", lambda values: ([], [], hist))
    monkeypatch.setattr(engine.ind, "atr", lambda highs, lows, closes, window: atr)


class TestSwingThresholds:
    BANDS = (90.0, 100.0, 110.0)  # %B = (price - 90) / 20

    @pytest.mark.parametrize(
        ("price", "rsi", "hist", "signal", "score"),
        [
            (93.0, 50, [-1.0, -0.5], "BUY_SETUP", 3),  # %B 0.15 < 0.2, rising
            (100.0, 34.9, [-1.0, -0.5], "BUY_SETUP", 3),  # RSI < 35, rising
            (94.0, 35.0, [-1.0, -0.5], "NO_SETUP", 1),  # %B exactly 0.2 / RSI exactly 35 -> not oversold
            (107.0, 50, [1.0, 0.5], "SELL_SETUP", 3),  # %B 0.85 > 0.8, falling
            (100.0, 65.1, [1.0, 0.5], "SELL_SETUP", 3),  # RSI > 65, falling
            (106.0, 65.0, [1.0, 0.5], "NO_SETUP", 0),  # %B exactly 0.8 / RSI exactly 65 -> not overbought
            (93.0, 50, [-0.5, -1.0], "NO_SETUP", 1),  # oversold but falling
            (107.0, 50, [0.5, 1.0], "NO_SETUP", 2),  # overbought but rising
            (100.0, 50, [0.5, 1.0], "NO_SETUP", 1),  # neutral, rising
            (100.0, 50, [1.0, 1.0], "NO_SETUP", 0),  # flat histogram is not rising
        ],
    )
    def test_rules_table(self, monkeypatch, price, rsi, hist, signal, score):
        _pin_swing(monkeypatch, bands=self.BANDS, rsi=rsi, hist=hist)
        s = evaluate_swing("TEST", make_bars([price]), AS_OF)
        assert (s.signal, s.score) == (signal, score)
        assert s.indicators["percent_b"] == round((price - 90) / 20, 3)
        assert s.rationale[-1].startswith("Rules: BUY_SETUP")

    def test_short_histogram_is_insufficient(self, monkeypatch):
        _pin_swing(monkeypatch, bands=self.BANDS, rsi=50, hist=[0.1])
        assert evaluate_swing("TEST", make_bars([100.0]), AS_OF).signal == INSUFFICIENT

    @pytest.mark.parametrize("field", ["bands", "rsi", "atr"])
    def test_missing_indicator_is_insufficient(self, monkeypatch, field):
        values = {"bands": self.BANDS, "rsi": 50, "hist": [0.1, 0.2], "atr": 1.0}
        values[field] = None
        _pin_swing(monkeypatch, **values)
        assert evaluate_swing("TEST", make_bars([100.0]), AS_OF).signal == INSUFFICIENT


# =========================================================================== income


def quarterly(start_year: int, end_year: int, first_annual: float, growth: float) -> list[tuple[str, float]]:
    out = []
    annual = first_annual
    for year in range(start_year, end_year + 1):
        out.extend((f"{year}-{m:02d}-15", annual / 4) for m in (2, 5, 8, 11))
        annual *= 1 + growth
    return out


class TestIncome:
    def test_attractive_full_score(self):
        divs = quarterly(2018, 2026, 1.00, 0.05)  # 2026 is incomplete and must be ignored
        s = evaluate_income(
            "TEST",
            make_quote(dividend_yield_pct=3.1),
            make_metrics(dividend_rate=2.0, payout_ratio_pct=60.0),
            divs,
            AS_OF,
        )
        assert (s.signal, s.score, s.max_score) == ("ATTRACTIVE", 4, 4)
        assert s.indicators["consecutive_growth_years"] == 7  # 2018 -> 2025
        assert s.indicators["dividend_cagr_5y_pct"] == 5.0
        assert s.indicators["dividend_rate"] == 2.0
        assert s.rationale == [
            "Dividend yield is at least 2.5% (+1).",
            "Payout ratio is 75% or lower: dividend appears covered by earnings (+1).",
            "Five-year dividend CAGR is positive (+1).",
            "Dividend has grown for at least five consecutive years (+1).",
            "Thresholds: yield < 1% or payout > 100% UNATTRACTIVE; score >= 3 ATTRACTIVE; otherwise ADEQUATE.",
        ]

    def test_attractive_at_score_three(self):
        divs = quarterly(2019, 2022, 1.0, 0.0) + quarterly(2023, 2025, 1.2, 0.05)  # flat 2019-22, step up after
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=2.5), make_metrics(payout_ratio_pct=75.0), divs, AS_OF
        )
        assert s.indicators["consecutive_growth_years"] == 3
        assert s.indicators["dividend_cagr_5y_pct"] > 0
        assert (s.score, s.signal) == (3, "ATTRACTIVE")

    def test_adequate(self):
        divs = quarterly(2023, 2025, 1.0, 0.0)  # flat, short history
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=1.8), make_metrics(payout_ratio_pct=40.0), divs, AS_OF
        )
        assert s.indicators["consecutive_growth_years"] == 0
        assert s.indicators["dividend_cagr_5y_pct"] is None
        assert (s.score, s.signal) == (1, "ADEQUATE")
        assert "Dividend yield is below 2.5% (0)." in s.rationale

    def test_adequate_at_score_two(self):
        divs = quarterly(2018, 2025, 1.0, 0.05)
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=1.0), make_metrics(payout_ratio_pct=80.0), divs, AS_OF
        )
        assert "Payout ratio is above 75%: limited coverage (0)." in s.rationale
        assert (s.score, s.signal) == (2, "ADEQUATE")  # yield exactly 1.0% is not < 1

    def test_low_yield_overrides_score(self):
        divs = quarterly(2018, 2025, 1.0, 0.05)
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=0.99), make_metrics(payout_ratio_pct=20.0), divs, AS_OF
        )
        assert s.score == 3
        assert s.signal == "UNATTRACTIVE"

    def test_uncovered_payout_overrides_score(self):
        divs = quarterly(2018, 2025, 1.0, 0.05)
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=4.0), make_metrics(payout_ratio_pct=100.1), divs, AS_OF
        )
        assert s.score == 3 and s.signal == "UNATTRACTIVE"
        s100 = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=4.0), make_metrics(payout_ratio_pct=100.0), divs, AS_OF
        )
        assert s100.signal == "ATTRACTIVE"

    def test_no_dividend_history(self):
        s = evaluate_income("TEST", make_quote(dividend_yield_pct=None), make_metrics(), [], AS_OF)
        assert (s.signal, s.score) == ("UNATTRACTIVE", 0)
        assert s.rationale == ["The company pays no regular dividend."]

    def test_zero_yield_with_history(self):
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=0.0), make_metrics(), quarterly(2020, 2025, 1, 0), AS_OF
        )
        assert s.signal == "UNATTRACTIVE" and s.rationale == ["The company pays no regular dividend."]

    def test_yield_without_history(self):
        s = evaluate_income("TEST", make_quote(dividend_yield_pct=3.0), make_metrics(), [], AS_OF)
        assert s.signal == "UNATTRACTIVE" and s.score == 0

    def test_missing_payout_ratio_adds_no_rationale(self):
        divs = quarterly(2018, 2025, 1.0, 0.05)
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=3.0), make_metrics(payout_ratio_pct=None), divs, AS_OF
        )
        assert not any("Payout ratio" in r for r in s.rationale)
        assert (s.score, s.signal) == (3, "ATTRACTIVE")

    def test_dividend_cut_resets_growth_streak(self):
        divs = quarterly(2015, 2023, 1.0, 0.05) + quarterly(2024, 2024, 0.5, 0) + quarterly(2025, 2025, 0.6, 0)
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=3.0), make_metrics(payout_ratio_pct=50.0), divs, AS_OF
        )
        assert s.indicators["consecutive_growth_years"] == 1
        assert s.indicators["dividend_cagr_5y_pct"] < 0
        assert (s.score, s.signal) == (2, "ADEQUATE")

    def test_gap_year_breaks_streak(self):
        divs = quarterly(2016, 2020, 1.0, 0.05) + quarterly(2022, 2025, 1.5, 0.05)  # nothing paid in 2021
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=3.0), make_metrics(payout_ratio_pct=50.0), divs, AS_OF
        )
        assert s.indicators["consecutive_growth_years"] == 3

    def test_cagr_needs_six_complete_years(self):
        divs = quarterly(2021, 2026, 1.0, 0.1)  # 2021-2025 complete = five years
        s = evaluate_income(
            "TEST", make_quote(dividend_yield_pct=3.0), make_metrics(payout_ratio_pct=50.0), divs, AS_OF
        )
        assert s.indicators["dividend_cagr_5y_pct"] is None
        assert s.indicators["consecutive_growth_years"] == 4

    def test_annual_dividends_excludes_current_year(self):
        totals = engine._annual_dividends([("2024-03-01", 0.5), ("2024-09-01", 0.5), ("2025-01-01", 9.0)], 2025)
        assert totals == {2024: 1.0}

    def test_offline_fixture_ko(self):
        from analyst.data import fixtures

        s = evaluate_income("KO", fixtures.quote("KO"), fixtures.metrics("KO"), fixtures.dividends("KO"), AS_OF)
        # Yield 2.86% (+1), payout 66% (+1), positive CAGR (+1), 2020-2025 = 5 growth years (+1)
        assert s.indicators["dividend_yield_pct"] == 2.86
        assert s.indicators["consecutive_growth_years"] == 5
        assert (s.score, s.signal) == (4, "ATTRACTIVE")


def test_strategy_signal_rejects_unknown_strategy():
    with pytest.raises(ValueError):
        engine.StrategySignal(
            ticker="X", strategy="yolo", signal="BUY", score=0, max_score=1, indicators={}, rationale=[], as_of=AS_OF
        )


def test_round_helper():
    assert engine._r(None) is None
    assert engine._r(1.23456) == 1.23
    assert engine._r(1.23456, 3) == 1.235
