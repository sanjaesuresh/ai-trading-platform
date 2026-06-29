"""Single-asset, long-only backtesting engine with next-bar-open execution.

Rules (Phase 1, preserved in Phase 2):
- Long-only, one position at a time, no margin or shorting.
- A signal computed from bar N's indicators fills at bar N+1's open — no
  look-ahead onto the same bar that produced the signal.
- A buy deploys a computed fraction of available cash (defaulting to
  ``max_position_pct`` when vol targeting is off); fees and slippage apply
  on every fill.
- Any position still open on the final bar is force-closed on that bar.
- Rows whose required indicators are still NaN produce HOLD (no trade).

Phase 2 additions (all opt-in — passing None preserves Phase 1 behaviour):
- Volatility-targeted position sizing via ``target_vol`` + ``vol_lookback``.
- Stop-loss and take-profit exits via ``stop_loss_pct`` / ``take_profit_pct``
  (close-trigger / next-open fill, same as every other signal).
- Max-drawdown circuit breaker via ``max_drawdown_cutoff_pct``: flattens the
  position and permanently halts new BUY entries for the rest of the run.

No-look-ahead guarantee (Phase 2):
- Sizing fraction is computed from returns through bar N's close and carried
  with the pending BUY order; the fill uses that pre-computed fraction at bar
  N+1's open — no bar N+1 data informs the sizing decision.
- Stop/target conditions are evaluated against bar N's close; the resulting
  SELL fills at bar N+1's open, mirroring every other exit.
- Drawdown is checked against the equity curve marked to bar N's close;
  the resulting flatten fills at bar N+1's open.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from app.backtesting.fees import calculate_fee
from app.backtesting.risk import ExitSignal, check_drawdown_breach, check_stop_target
from app.backtesting.sizing import compute_position_fraction
from app.backtesting.slippage import apply_slippage
from app.strategies.base_strategy import BaseStrategy, Position, StrategySignal

# Use stdlib getLogger so this module can be imported in pure-logic tests without
# triggering the settings loader (which requires DATABASE_URL).  At runtime the
# root logger is configured by app.core.logging.configure_logging via app startup.
log = logging.getLogger(__name__)


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
    halted: bool = False
    halt_timestamp: pd.Timestamp | None = None


def run_backtest(
    frame: pd.DataFrame,
    strategy: BaseStrategy,
    symbol: str,
    initial_capital: float = 100_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    max_position_pct: float = 0.95,
    # --- Phase 2 optional risk/sizing params (all default to None = opt-in off) ---
    target_vol: float | None = None,
    vol_lookback: int = 20,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    max_drawdown_cutoff_pct: float | None = None,
) -> BacktestResult:
    """Walk the frame bar by bar and produce trades plus the equity curve.

    Backward compatibility: when all Phase 2 params are ``None`` (the
    default), behaviour is identical to the Phase 1 engine.
    """
    state = _State(cash=float(initial_capital), peak_equity=float(initial_capital))
    pending: StrategySignal | None = None
    pending_reason = ""
    # Fraction of cash to deploy on the next BUY fill.  Pre-computed at
    # decision time (bar N) so the fill at bar N+1 uses no look-ahead data.
    pending_fraction: float = float(max_position_pct)

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
            _execute_buy(
                state, symbol, ts, open_price, slippage_bps, fee_bps,
                pending_fraction, fee_rate, pending_reason,
            )
        elif pending == StrategySignal.SELL and state.position.is_open:
            _execute_sell(state, symbol, ts, open_price, slippage_bps, fee_bps,
                          pending_reason)

        pending = None
        pending_reason = ""
        pending_fraction = float(max_position_pct)

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

        # 4. Update the running equity peak (used by the drawdown circuit breaker).
        if equity > state.peak_equity:
            state.peak_equity = equity

        # 5. Decide for the next bar (the final bar has no next bar to fill on).
        if not is_final:
            # A. Stop/target: highest-priority exit for an open position.
            #    Condition evaluated at bar N's close; fill will be at bar N+1's open.
            if state.position.is_open and (
                stop_loss_pct is not None or take_profit_pct is not None
            ):
                exit_sig = check_stop_target(
                    state.position.entry_price, close_price,
                    stop_loss_pct, take_profit_pct,
                )
                if exit_sig is not None:
                    pending = StrategySignal.SELL
                    pending_reason = (
                        "stop-loss" if exit_sig == ExitSignal.STOP else "take-profit"
                    )

            # B. Max-drawdown circuit breaker.
            #    Sets the permanent halt flag and queues a flatten if no exit is
            #    already pending.  The halt is permanent for the rest of this run.
            if (
                max_drawdown_cutoff_pct is not None
                and not state.halted
                and check_drawdown_breach(state.peak_equity, equity, max_drawdown_cutoff_pct)
            ):
                    state.halted = True
                    state.halt_timestamp = ts
                    log.info(
                        "Max-drawdown circuit breaker tripped at %s; "
                        "all new BUY entries suppressed for the rest of this run.",
                        ts,
                    )
                    # Flatten if no exit already queued and a position is open.
                    if pending is None and state.position.is_open:
                        pending = StrategySignal.SELL
                        pending_reason = "max-drawdown halt"

            # C. Strategy signal — only when no exit is already pending.
            #    Strategy SELL exits still execute while halted; BUYs are suppressed.
            if pending is None:
                decision = strategy.generate_signal(row, state.position)
                if decision.action == StrategySignal.SELL:
                    # Exits execute even when halted.
                    pending = StrategySignal.SELL
                    pending_reason = decision.reason
                elif decision.action == StrategySignal.BUY and not state.halted:
                    pending = StrategySignal.BUY
                    pending_reason = decision.reason
                    # Compute the sizing fraction at decision time (bar i) so the
                    # fill at bar i+1 carries no look-ahead information.
                    if target_vol is not None:
                        if i >= vol_lookback:
                            # Slice: vol_lookback+1 closes → vol_lookback returns.
                            closes = frame["close"].iloc[
                                i - vol_lookback : i + 1
                            ].to_numpy(dtype=float)
                            returns = closes[1:] / closes[:-1] - 1.0
                            pending_fraction = compute_position_fraction(
                                returns, target_vol, float(max_position_pct)
                            )
                        else:
                            # Under vol targeting, refuse to enter before a full
                            # lookback window exists to size against — skip rather
                            # than max-size on an unmeasurable risk budget. This is
                            # the same honesty rule as compute_position_fraction's
                            # un-estimable-vol case (return 0.0, do not trade).
                            pending_fraction = 0.0
                    # else (no vol targeting): pending_fraction stays max_position_pct
                    # → Phase 1 flat sizing, unchanged.

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
        halted=state.halted,
        halt_timestamp=state.halt_timestamp,
    )


@dataclass
class _State:
    cash: float
    position: Position = field(default_factory=Position)
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    # Running equity peak for the max-drawdown circuit breaker.
    peak_equity: float = 0.0
    # Permanent halt flag: set when max_drawdown_cutoff_pct is breached.
    halted: bool = False
    halt_timestamp: pd.Timestamp | None = None


def _execute_buy(
    state: _State, symbol: str, ts: pd.Timestamp, open_price: float,
    slippage_bps: float, fee_bps: float, fraction: float, fee_rate: float,
    reason: str,
) -> None:
    fill = apply_slippage(open_price, "BUY", slippage_bps)
    # Size so that gross + fee never exceeds the cash budget.
    budget = state.cash * fraction
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
