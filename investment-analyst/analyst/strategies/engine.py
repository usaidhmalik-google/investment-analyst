"""Deterministic multi-strategy evaluation (Momentum, Value, Swing, Income).

Each evaluator is a pure function of already-fetched data so that signal generation
is reproducible and 100% testable (Scope North Star: Multi-Strategy Coverage).
Thresholds are explicit constants documented in the rationale returned to the LLM.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ..data.schemas import FinancialMetrics, PriceBar, Quote, StrategySignal
from . import indicators as ind

INSUFFICIENT = "INSUFFICIENT_DATA"


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def evaluate_momentum(ticker: str, bars: Sequence[PriceBar], as_of: str) -> StrategySignal:
    closes = [b.close for b in bars]
    price = closes[-1] if closes else None
    sma50, sma200 = ind.sma(closes, 50), ind.sma(closes, 200)
    rsi14 = ind.rsi(closes, 14)
    roc63, roc126 = ind.rate_of_change(closes, 63), ind.rate_of_change(closes, 126)
    indicators = {
        "price": _r(price),
        "sma_50": _r(sma50),
        "sma_200": _r(sma200),
        "rsi_14": _r(rsi14),
        "roc_3m_pct": _r(roc63),
        "roc_6m_pct": _r(roc126),
    }
    if price is None or sma50 is None or sma200 is None or rsi14 is None or roc63 is None:
        return StrategySignal(
            ticker=ticker, strategy="momentum", signal=INSUFFICIENT, score=0, max_score=6,
            indicators=indicators, rationale=["Momentum needs at least 200 daily bars."], as_of=as_of,
        )  # fmt: skip
    score, why = 0, []
    if price > sma50:
        score += 1
        why.append("Price is above its 50-day SMA (+1).")
    else:
        why.append("Price is below its 50-day SMA (0).")
    if price > sma200:
        score += 1
        why.append("Price is above its 200-day SMA (+1).")
    else:
        why.append("Price is below its 200-day SMA (0).")
    golden = sma50 > sma200
    indicators["golden_cross"] = golden
    if golden:
        score += 1
        why.append("50-day SMA is above the 200-day SMA (golden-cross regime, +1).")
    else:
        why.append("50-day SMA is below the 200-day SMA (death-cross regime, 0).")
    if 50 <= rsi14 <= 70:
        score += 1
        why.append("RSI(14) is between 50 and 70: positive momentum without being overbought (+1).")
    elif rsi14 > 70:
        why.append("RSI(14) is above 70: overbought, momentum may be stretched (0).")
    else:
        why.append("RSI(14) is below 50: weak momentum (0).")
    if roc63 > 0:
        score += 1
        why.append("3-month rate of change is positive (+1).")
    else:
        why.append("3-month rate of change is negative (0).")
    if roc126 is not None and roc126 > 0:
        score += 1
        why.append("6-month rate of change is positive (+1).")
    else:
        why.append("6-month rate of change is negative or unavailable (0).")
    signal = "BULLISH" if score >= 5 else "BEARISH" if score <= 2 else "NEUTRAL"
    why.append("Thresholds: score >= 5 BULLISH, <= 2 BEARISH, otherwise NEUTRAL.")
    return StrategySignal(
        ticker=ticker, strategy="momentum", signal=signal, score=score, max_score=6,
        indicators=indicators, rationale=why, as_of=as_of,
    )  # fmt: skip


def evaluate_value(ticker: str, quote: Quote, metrics: FinancialMetrics, as_of: str) -> StrategySignal:
    fcf_yield = (
        metrics.free_cash_flow / quote.market_cap * 100
        if metrics.free_cash_flow is not None and quote.market_cap
        else None
    )
    indicators = {
        "trailing_pe": quote.trailing_pe,
        "forward_pe": quote.forward_pe,
        "price_to_book": metrics.price_to_book,
        "peg_ratio": metrics.peg_ratio,
        "fcf_yield_pct": _r(fcf_yield),
        "debt_to_equity": metrics.debt_to_equity,
    }
    available = [v for v in indicators.values() if v is not None]
    if len(available) < 3:
        return StrategySignal(
            ticker=ticker, strategy="value", signal=INSUFFICIENT, score=0, max_score=6,
            indicators=indicators, rationale=["Value needs at least three valuation inputs."], as_of=as_of,
        )  # fmt: skip
    score, why = 0, []
    pe = quote.trailing_pe
    if pe is not None:
        if pe <= 0:
            why.append("Trailing P/E is not meaningful (zero or negative earnings) (0).")
        elif pe < 15:
            score += 1
            why.append("Trailing P/E is below 15 (+1).")
        elif pe > 30:
            score -= 1
            why.append("Trailing P/E is above 30 (-1).")
        else:
            why.append("Trailing P/E is between 15 and 30 (0).")
    if pe is not None and quote.forward_pe is not None and 0 < quote.forward_pe < pe:
        score += 1
        why.append("Forward P/E is below trailing P/E, implying expected earnings growth (+1).")
    if metrics.price_to_book is not None:
        if metrics.price_to_book <= 0:
            why.append("Price-to-book is not meaningful (zero or negative book value) (0).")
        elif metrics.price_to_book < 3:
            score += 1
            why.append("Price-to-book is below 3 (+1).")
        else:
            why.append("Price-to-book is 3 or higher (0).")
    if metrics.peg_ratio is not None:
        if metrics.peg_ratio <= 0:
            why.append("PEG ratio is not meaningful (zero or negative growth/earnings) (0).")
        elif metrics.peg_ratio < 1:
            score += 1
            why.append("PEG ratio is below 1 (+1).")
        elif metrics.peg_ratio > 2:
            score -= 1
            why.append("PEG ratio is above 2 (-1).")
        else:
            why.append("PEG ratio is between 1 and 2 (0).")
    if fcf_yield is not None:
        if fcf_yield > 5:
            score += 1
            why.append("Free-cash-flow yield is above 5% (+1).")
        elif fcf_yield < 2:
            score -= 1
            why.append("Free-cash-flow yield is below 2% (-1).")
        else:
            why.append("Free-cash-flow yield is between 2% and 5% (0).")
    if metrics.debt_to_equity is not None:
        if metrics.debt_to_equity < 0:
            why.append("Debt-to-equity is negative (negative shareholders' equity) (0).")
        elif metrics.debt_to_equity < 1:
            score += 1
            why.append("Debt-to-equity is below 1.0x (+1).")
        else:
            why.append("Debt-to-equity is 1.0x or higher (0).")
    signal = "UNDERVALUED" if score >= 3 else "OVERVALUED" if score <= 0 else "FAIRLY_VALUED"
    why.append("Thresholds: score >= 3 UNDERVALUED, <= 0 OVERVALUED, otherwise FAIRLY_VALUED.")
    return StrategySignal(
        ticker=ticker, strategy="value", signal=signal, score=score, max_score=6,
        indicators=indicators, rationale=why, as_of=as_of,
    )  # fmt: skip


def evaluate_swing(ticker: str, bars: Sequence[PriceBar], as_of: str) -> StrategySignal:
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    price = closes[-1] if closes else None
    bands = ind.bollinger(closes, 20, 2.0)
    rsi14 = ind.rsi(closes, 14)
    _, _, hist = ind.macd(closes)
    atr14 = ind.atr(highs, lows, closes, 14)
    if price is None or bands is None or rsi14 is None or len(hist) < 2 or atr14 is None:
        return StrategySignal(
            ticker=ticker, strategy="swing", signal=INSUFFICIENT, score=0, max_score=3,
            indicators={"price": _r(price)}, rationale=["Swing needs at least 35 daily bars."], as_of=as_of,
        )  # fmt: skip
    pct_b = ind.percent_b(price, bands)
    hist_rising = hist[-1] > hist[-2]
    indicators = {
        "price": _r(price),
        "bollinger_lower": _r(bands[0]),
        "bollinger_middle": _r(bands[1]),
        "bollinger_upper": _r(bands[2]),
        "percent_b": _r(pct_b, 3),
        "rsi_14": _r(rsi14),
        "macd_histogram": _r(hist[-1], 3),
        "macd_histogram_rising": hist_rising,
        "atr_14": _r(atr14),
        "atr_pct_of_price": _r(atr14 / price * 100),
        "support_20d": _r(min(lows[-20:])),
        "resistance_20d": _r(max(highs[-20:])),
    }
    oversold = (pct_b is not None and pct_b < 0.2) or rsi14 < 35
    overbought = (pct_b is not None and pct_b > 0.8) or rsi14 > 65
    why = []
    if oversold and hist_rising:
        signal, score = "BUY_SETUP", 3
        why.append("Price is near the lower Bollinger band or RSI(14) < 35 while MACD histogram is rising.")
    elif overbought and not hist_rising:
        signal, score = "SELL_SETUP", 3
        why.append("Price is near the upper Bollinger band or RSI(14) > 65 while MACD histogram is falling.")
    else:
        signal, score = "NO_SETUP", int(oversold or overbought) + int(hist_rising)
        why.append("No confluence between band position/RSI extremes and MACD histogram direction.")
    why.append(
        "Rules: BUY_SETUP = (%B < 0.2 or RSI < 35) and MACD hist rising; "
        "SELL_SETUP = (%B > 0.8 or RSI > 65) and MACD hist falling."
    )
    return StrategySignal(
        ticker=ticker, strategy="swing", signal=signal, score=score, max_score=3,
        indicators=indicators, rationale=why, as_of=as_of,
    )  # fmt: skip


def _annual_dividends(dividends: Sequence[tuple[str, float]], as_of_year: int) -> dict[int, float]:
    totals: dict[int, float] = defaultdict(float)
    for day, amount in dividends:
        year = int(day[:4])
        if year < as_of_year:  # only complete calendar years
            totals[year] += amount
    return dict(totals)


def evaluate_income(
    ticker: str, quote: Quote, metrics: FinancialMetrics, dividends: Sequence[tuple[str, float]], as_of: str
) -> StrategySignal:
    as_of_year = int(as_of[:4])
    annual = _annual_dividends(dividends, as_of_year)
    years = sorted(annual)
    growth_years = 0
    for prev, cur in zip(reversed(years[:-1]), reversed(years[1:]), strict=True):
        if annual[cur] > annual[prev] and cur - prev == 1:
            growth_years += 1
        else:
            break
    cagr5 = None
    if len(years) >= 6:
        cagr5 = ind.cagr(annual[years[-6]], annual[years[-1]], 5)
    yld = quote.dividend_yield_pct
    payout = metrics.payout_ratio_pct
    indicators = {
        "dividend_yield_pct": yld,
        "dividend_rate": metrics.dividend_rate,
        "payout_ratio_pct": payout,
        "dividend_cagr_5y_pct": _r(cagr5),
        "consecutive_growth_years": growth_years,
    }
    why = []
    if not dividends or not yld:
        why.append("The company pays no regular dividend.")
        return StrategySignal(
            ticker=ticker, strategy="income", signal="UNATTRACTIVE", score=0, max_score=4,
            indicators=indicators, rationale=why, as_of=as_of,
        )  # fmt: skip
    score = 0
    if yld >= 2.5:
        score += 1
        why.append("Dividend yield is at least 2.5% (+1).")
    else:
        why.append("Dividend yield is below 2.5% (0).")
    if payout is not None and payout <= 75:
        score += 1
        why.append("Payout ratio is 75% or lower: dividend appears covered by earnings (+1).")
    elif payout is not None:
        why.append("Payout ratio is above 75%: limited coverage (0).")
    if cagr5 is not None and cagr5 > 0:
        score += 1
        why.append("Five-year dividend CAGR is positive (+1).")
    if growth_years >= 5:
        score += 1
        why.append("Dividend has grown for at least five consecutive years (+1).")
    if yld < 1 or (payout is not None and payout > 100):
        signal = "UNATTRACTIVE"
    elif score >= 3:
        signal = "ATTRACTIVE"
    else:
        signal = "ADEQUATE"
    why.append("Thresholds: yield < 1% or payout > 100% UNATTRACTIVE; score >= 3 ATTRACTIVE; otherwise ADEQUATE.")
    return StrategySignal(
        ticker=ticker, strategy="income", signal=signal, score=score, max_score=4,
        indicators=indicators, rationale=why, as_of=as_of,
    )  # fmt: skip
