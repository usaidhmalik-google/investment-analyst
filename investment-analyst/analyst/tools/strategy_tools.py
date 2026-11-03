"""Strategy Evaluator tool: deterministic Momentum / Value / Swing / Income signals."""

from __future__ import annotations

from typing import Any

from google.adk.tools.tool_context import ToolContext

from ..config import STRATEGIES
from ..data import market
from ..strategies import engine
from .evidence import dump, record_evidence, safe_tool


@safe_tool
def evaluate_strategy(ticker: str, strategy: str, tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Evaluate a stock against an investment strategy using deterministic, rules-based indicators.

    Strategies:
      - "momentum": 50/200-day SMAs, golden cross, RSI(14), 3- and 6-month rate of change.
      - "value": trailing/forward P/E, price-to-book, PEG, free-cash-flow yield, debt-to-equity.
      - "swing": Bollinger Bands(20, 2), %B, RSI(14), MACD(12, 26, 9) histogram, ATR(14), 20-day support/resistance.
      - "income": dividend yield, payout ratio, 5-year dividend CAGR, consecutive growth years.

    Args:
        ticker: Stock ticker symbol.
        strategy: One of "momentum", "value", "swing", "income".

    Returns:
        The signal, score, indicator values and rule-by-rule rationale; cite as ``[S:TICKER:strategy]``.
    """
    strategy = strategy.strip().lower()
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {STRATEGIES}")
    symbol = market.normalize_ticker(ticker)
    if strategy in ("momentum", "swing"):
        history = market.get_history(symbol, "1y")
        as_of = history.as_of
        signal = (
            engine.evaluate_momentum(symbol, history.bars, as_of)
            if strategy == "momentum"
            else engine.evaluate_swing(symbol, history.bars, as_of)
        )
    else:
        quote = market.get_quote(symbol)
        metrics = market.get_metrics(symbol)
        as_of = quote.as_of
        if strategy == "value":
            signal = engine.evaluate_value(symbol, quote, metrics, as_of)
        else:
            signal = engine.evaluate_income(symbol, quote, metrics, market.get_dividends(symbol), as_of)
    return record_evidence(
        tool_context,
        citation_id=f"S:{symbol}:{strategy}",
        type="strategy",
        title=f"{symbol} {strategy} strategy evaluation: {signal.signal}",
        source=signal.source,
        as_of=signal.as_of,
        data=dump(signal),
    )


STRATEGY_TOOLS = [evaluate_strategy]
