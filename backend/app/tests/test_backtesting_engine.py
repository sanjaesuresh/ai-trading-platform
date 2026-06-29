"""Engine: equity curve, trades, fees, slippage, no double-buy, final force-close."""

from __future__ import annotations

import pandas as pd
import pytest

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
        return StrategyDecision(action=self._action, reason=f"scripted {self._action.value}")


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
    # Exactly one buy fill plus the forced sell — no extra fills while holding.
    assert len(result.trades) == 2


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
    # The buy fills at bar index 1 (open=200), slipped upward by 10 bps.
    assert buy.price == pytest.approx(200.0 * 1.001)
    assert buy.fee == pytest.approx(buy.gross_value * 5 / 10_000)
    assert buy.slippage == pytest.approx(abs(buy.price - 200.0) * buy.quantity)


def test_sell_side_fee_and_slippage_applied() -> None:
    # Force-close on the final bar exercises the SELL path: fills below the raw
    # price (slipped down) and still pays a fee.
    frame = _frame([100, 200, 300, 400, 500])
    result = run_backtest(frame, _ScriptedStrategy(StrategySignal.BUY), "T",
                          initial_capital=10_000, fee_bps=5, slippage_bps=10)
    sell = next(t for t in result.trades if t.side == "SELL")
    final_close = float(frame["close"].iloc[-1])
    assert sell.price == pytest.approx(final_close * 0.999)
    assert sell.price < final_close
    assert sell.fee == pytest.approx(sell.gross_value * 5 / 10_000)
    assert sell.slippage > 0.0


def test_buy_fill_timestamp_is_next_bar() -> None:
    # A signal from bar 0 must fill at bar 1's open — proves next-bar execution.
    frame = _frame([100, 102, 104, 106, 108])
    result = run_backtest(frame, _ScriptedStrategy(StrategySignal.BUY), "T",
                          initial_capital=10_000, fee_bps=5, slippage_bps=5)
    buy = next(t for t in result.trades if t.side == "BUY")
    assert buy.timestamp == frame["timestamp"].iloc[1]


def test_single_bar_frame_produces_no_trades() -> None:
    frame = _frame([100])
    result = run_backtest(frame, _ScriptedStrategy(StrategySignal.BUY), "T",
                          initial_capital=10_000, fee_bps=5, slippage_bps=5)
    assert len(result.equity_curve) == 1
    assert result.trades == []
    assert result.final_equity == 10_000.0


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
