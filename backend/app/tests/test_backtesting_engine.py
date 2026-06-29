"""Engine: equity curve, trades, fees, slippage, no double-buy, final force-close."""

from __future__ import annotations

import pandas as pd

from app.backtesting.engine import run_backtest
from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)


class _ScriptedStrategy(BaseStrategy):
    """Returns a fixed action on every bar, to exercise engine mechanics."""

    name = "scripted"

    def __init__(self, action: StrategySignal) -> None:
        self._action = action

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        return StrategyDecision(
            timestamp=row["timestamp"], symbol=str(row.get("symbol", "")),
            action=self._action, confidence=0.7, reason=f"scripted {self._action.value}",
        )


def _frame(opens: list[float]) -> pd.DataFrame:
    n = len(opens)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=n, freq="D"),
            "open": opens,
            "high": [o + 1 for o in opens],
            "low": [o - 1 for o in opens],
            "close": opens,
            "volume": [1_000.0] * n,
        }
    )


def test_equity_curve_and_trades_recorded() -> None:
    frame = _frame([100, 102, 104, 106, 108])
    result = run_backtest(frame, _ScriptedStrategy(StrategySignal.BUY), "T",
                          initial_capital=10_000, fee_bps=5, slippage_bps=5)
    assert len(result.equity_curve) == len(frame)
    assert len(result.trades) >= 2  # one buy fill plus the forced sell


def test_no_double_buy_while_in_position() -> None:
    # BUY signalled every bar, but only one buy should fill while holding.
    frame = _frame([100, 102, 104, 106, 108])
    result = run_backtest(frame, _ScriptedStrategy(StrategySignal.BUY), "T",
                          initial_capital=10_000, fee_bps=5, slippage_bps=5)
    buys = [t for t in result.trades if t.side == "BUY"]
    assert len(buys) == 1


def test_fee_and_slippage_applied() -> None:
    frame = _frame([100, 200, 300, 400, 500])
    result = run_backtest(frame, _ScriptedStrategy(StrategySignal.BUY), "T",
                          initial_capital=10_000, fee_bps=5, slippage_bps=10)
    buy = next(t for t in result.trades if t.side == "BUY")
    # The buy fills at bar index 1 (open=200), slipped upward.
    assert buy.price > 200.0
    assert buy.fee > 0.0
    assert buy.slippage > 0.0


def test_force_close_on_final_bar() -> None:
    frame = _frame([100, 102, 104, 106, 108])
    result = run_backtest(frame, _ScriptedStrategy(StrategySignal.BUY), "T",
                          initial_capital=10_000, fee_bps=5, slippage_bps=5)
    last_trade = result.trades[-1]
    assert last_trade.side == "SELL"
    assert last_trade.timestamp == frame["timestamp"].iloc[-1]
    assert last_trade.position_after == 0.0


def test_no_sell_without_position() -> None:
    # SELL every bar but never a position -> no trades at all.
    frame = _frame([100, 102, 104, 106, 108])
    result = run_backtest(frame, _ScriptedStrategy(StrategySignal.SELL), "T",
                          initial_capital=10_000, fee_bps=5, slippage_bps=5)
    assert result.trades == []
    assert result.final_equity == 10_000.0
