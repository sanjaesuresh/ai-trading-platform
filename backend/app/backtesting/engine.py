"""Single-asset, long-only backtesting engine with next-bar-open execution.

Rules (Phase 1):
- Long-only, one position at a time, no margin or shorting.
- A signal computed from bar N's indicators fills at bar N+1's open — no
  look-ahead onto the same bar that produced the signal.
- A buy deploys ``max_position_pct`` of available cash; fees and slippage apply
  on every fill.
- Any position still open on the final bar is force-closed on that bar.
- Rows whose required indicators are still NaN produce HOLD (no trade).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from app.backtesting.fees import calculate_fee
from app.backtesting.slippage import apply_slippage
from app.strategies.base_strategy import BaseStrategy, Position, StrategySignal


@dataclass
class TradeRecord:
    symbol: str
    side: str  # "BUY" or "SELL"
    timestamp: pd.Timestamp
    price: float  # effective fill price after slippage
    quantity: float
    gross_value: float
    fee: float
    slippage: float  # slippage cost in currency
    cash_after: float
    position_after: float
    equity_after: float
    reason: str


@dataclass
class EquityPoint:
    timestamp: pd.Timestamp
    equity: float
    cash: float
    position_value: float


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def run_backtest(
    frame: pd.DataFrame,
    strategy: BaseStrategy,
    symbol: str,
    initial_capital: float = 100_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    max_position_pct: float = 0.95,
) -> BacktestResult:
    """Walk the frame bar by bar and produce trades plus the equity curve."""
    started_at = datetime.now(UTC)

    state = _State(cash=float(initial_capital))
    pending: StrategySignal | None = None
    pending_reason = ""

    n = len(frame)
    fee_rate = fee_bps / 10_000.0

    for i in range(n):
        row = frame.iloc[i]
        open_price = float(row["open"])
        close_price = float(row["close"])
        ts = row["timestamp"]
        is_final = i == n - 1

        # 1. Fill the order decided on the previous bar, at this bar's open.
        if pending == StrategySignal.BUY and not state.position.is_open:
            _execute_buy(state, symbol, ts, open_price, slippage_bps, fee_bps,
                         max_position_pct, fee_rate, pending_reason)
        elif pending == StrategySignal.SELL and state.position.is_open:
            _execute_sell(state, symbol, ts, open_price, slippage_bps, fee_bps,
                          pending_reason)

        pending = None
        pending_reason = ""

        # 2. Force-close any open position on the final bar (no next bar to fill on).
        if is_final and state.position.is_open:
            _execute_sell(state, symbol, ts, close_price, slippage_bps, fee_bps,
                          "Force-close open position on final bar.")

        # 3. Mark equity to this bar's close.
        position_value = state.position.quantity * close_price
        equity = state.cash + position_value
        state.equity_curve.append(
            EquityPoint(timestamp=ts, equity=equity, cash=state.cash,
                        position_value=position_value)
        )

        # 4. Decide for the next bar (the final bar has no next bar to fill on).
        if not is_final:
            decision = strategy.generate_signal(row, state.position)
            if decision.action in (StrategySignal.BUY, StrategySignal.SELL):
                pending = decision.action
                pending_reason = decision.reason

    final_equity = state.equity_curve[-1].equity if state.equity_curve else float(initial_capital)
    total_return_pct = (
        (final_equity - initial_capital) / initial_capital * 100.0 if initial_capital else 0.0
    )

    return BacktestResult(
        symbol=symbol,
        strategy_name=strategy.name,
        initial_capital=float(initial_capital),
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        equity_curve=state.equity_curve,
        trades=state.trades,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


@dataclass
class _State:
    cash: float
    position: Position = field(default_factory=Position)
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)


def _execute_buy(
    state: _State, symbol: str, ts: pd.Timestamp, open_price: float,
    slippage_bps: float, fee_bps: float, max_position_pct: float, fee_rate: float,
    reason: str,
) -> None:
    fill = apply_slippage(open_price, "BUY", slippage_bps)
    # Size so that gross + fee never exceeds the cash budget.
    budget = state.cash * max_position_pct
    quantity = budget / (fill * (1.0 + fee_rate))
    if quantity <= 0:
        return
    gross = quantity * fill
    fee = calculate_fee(gross, fee_bps)
    slip_cost = abs(fill - open_price) * quantity
    state.cash -= gross + fee
    state.position = Position(quantity=quantity, entry_price=fill)
    equity_after = state.cash + quantity * fill
    state.trades.append(
        TradeRecord(
            symbol=symbol, side="BUY", timestamp=ts, price=fill, quantity=quantity,
            gross_value=gross, fee=fee, slippage=slip_cost, cash_after=state.cash,
            position_after=quantity, equity_after=equity_after, reason=reason,
        )
    )


def _execute_sell(
    state: _State, symbol: str, ts: pd.Timestamp, raw_price: float,
    slippage_bps: float, fee_bps: float, reason: str,
) -> None:
    quantity = state.position.quantity
    fill = apply_slippage(raw_price, "SELL", slippage_bps)
    gross = quantity * fill
    fee = calculate_fee(gross, fee_bps)
    slip_cost = abs(raw_price - fill) * quantity
    state.cash += gross - fee
    state.position = Position()
    state.trades.append(
        TradeRecord(
            symbol=symbol, side="SELL", timestamp=ts, price=fill, quantity=quantity,
            gross_value=gross, fee=fee, slippage=slip_cost, cash_after=state.cash,
            position_after=0.0, equity_after=state.cash, reason=reason,
        )
    )
