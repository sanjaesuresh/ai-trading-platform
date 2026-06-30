"""Pure, I/O-free portfolio execution core (Phase 3, M1).

The keystone of Phase 3: a single allocation / sizing / risk / fill core that
**both** the multi-symbol backtest driver and the live paper-trading runner drive,
so live behaviour is exactly what can be backtested ("live must equal
backtested"). The function ``evaluate_portfolio`` is the shared decision unit —
given the current state, the latest per-symbol bars, and per-symbol strategy
decisions, it returns the set of target orders under portfolio risk limits. The
M3 equivalence test asserts the backtest driver and the live runner get the same
orders from it for the same bars.

Invariants carried from Phase 1/2, now portfolio-wide:
- Long-only, one position per symbol, no margin or shorting.
- A signal computed from bar N's close fills at bar N+1's open — no look-ahead.
- Fees and slippage apply on every fill.
- Any position open on the final backtest bar is force-closed there (driver).

No-look-ahead guarantee: the vol-sizing window and the deterministic ranking
metric are computed from returns through bar N's close and carried with the
target order; the fill uses that pre-computed notional at bar N+1's open. No bar
N+1 data informs any sizing or selection decision.

What does NOT live here: any I/O, broker call, database call, or pandas
dependency on the hot path. The driver extracts scalars into ``SymbolContext``.

Known, unmodeled biases (directional, documented, not papered over):
- Slippage is a flat bps applied per fill with no size / ADV / market-impact
  term (``app.backtesting.slippage``). Across a shared-cash basket that can
  concentrate up to the gross cap and rotate names, this understates real cost;
  a portfolio result is only valid at the AUM and turnover it was simulated at.
- The gross-exposure cap is enforced on bar-N marks while fills land at the N+1
  open, so realized gross exposure can drift slightly past the cap on a gap up.
  This is the honest direction (size on what is known at N), not a hard invariant.
These are the kind of biases §13.2 of the Phase 3 plan calls to align / measure /
calibrate once live paper fills are observed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.backtesting.fees import calculate_fee
from app.backtesting.records import EquityPoint, TradeRecord
from app.backtesting.risk import ExitSignal, check_drawdown_breach, check_stop_target
from app.backtesting.sizing import compute_position_fraction
from app.backtesting.slippage import apply_slippage
from app.strategies.base_strategy import StrategyDecision, StrategySignal

if TYPE_CHECKING:
    import pandas as pd

# Re-exported so callers (driver, metrics) have one import home for the record
# shapes, which are shared across the single-symbol engine and portfolio layer.
__all__ = [
    "EquityPoint",
    "PortfolioConfig",
    "PortfolioDecision",
    "PortfolioPosition",
    "PortfolioState",
    "SymbolContext",
    "TargetOrder",
    "TradeRecord",
    "apply_buy_fill",
    "apply_sell_fill",
    "build_symbol_context",
    "evaluate_portfolio",
    "portfolio_equity",
    "position_value",
    "trailing_returns_at",
]


@dataclass
class PortfolioPosition:
    """One long position in the portfolio. Long-only, one per symbol."""

    symbol: str
    quantity: float = 0.0
    entry_price: float = 0.0  # effective fill price after slippage

    @property
    def is_open(self) -> bool:
        return self.quantity > 0.0


@dataclass
class PortfolioState:
    """Mutable portfolio state: shared cash, a position per symbol, and the
    running equity peak + permanent halt flag used by the drawdown kill switch.
    """

    cash: float
    positions: dict[str, PortfolioPosition] = field(default_factory=dict)
    # Running equity peak for the portfolio max-drawdown circuit breaker.
    peak_equity: float = 0.0
    # Permanent halt: set when the portfolio drawdown kill trips. While halted,
    # every open position is flattened and no new BUY entry is taken.
    halted: bool = False
    halt_reason: str = ""

    def open_symbols(self) -> list[str]:
        """Symbols currently holding a long position, sorted for determinism."""
        return sorted(s for s, p in self.positions.items() if p.is_open)


@dataclass(frozen=True)
class PortfolioConfig:
    """Portfolio backtest / live configuration.

    A plain frozen dataclass (no Pydantic) to keep the core I/O- and
    dependency-free; the M4 API schema validates and constructs it.
    """

    initial_capital: float = 100_000.0
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    # Per-symbol volatility-targeted sizing (opt-in: None reuses flat sizing).
    target_vol: float | None = None
    vol_lookback: int = 20
    max_position_pct: float = 0.95  # per-symbol cap on the deployed fraction
    # Portfolio-level risk limits.
    gross_exposure_cap: float = 1.0  # fraction of equity (1.0 = cash, no leverage)
    max_open_positions: int = 5
    per_order_notional_cap: float | None = None
    # Per-symbol exits (same close-trigger / next-open model as the engine).
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    # Portfolio max-drawdown kill: flatten all + halt new entries past threshold.
    max_drawdown_cutoff_pct: float | None = None


@dataclass(frozen=True)
class SymbolContext:
    """Everything the core needs about one symbol at the current decision bar.

    The driver extracts these scalars from bar N so the core stays pandas-free.
    ``trailing_returns`` is the close-to-close window used for vol sizing and the
    ranking metric; it is the full ``vol_lookback`` window when available and
    empty during warm-up (the same honesty rule as the single-symbol engine:
    refuse to size on an incomplete risk window).
    """

    symbol: str
    close: float  # bar-N close: the decision/mark price
    decision: StrategySignal  # strategy action at bar N
    reason: str
    trailing_returns: tuple[float, ...] = ()


@dataclass(frozen=True)
class TargetOrder:
    """A target order emitted by the core, filled by the driver at next open.

    BUY carries the cash ``notional`` budget to deploy (computed from equity and
    the vol-target weight at decision time — identical across backtest and live).
    SELL closes the full position, so ``notional`` is unused (0.0).
    """

    symbol: str
    side: str  # "BUY" or "SELL"
    notional: float
    reason: str


@dataclass
class PortfolioDecision:
    """The core's decision for one step: the orders plus whether the drawdown
    kill newly tripped this step (the driver applies the halt to state)."""

    orders: list[TargetOrder]
    halt_triggered: bool
    halt_reason: str
    equity: float
    gross_exposure_pct: float


def position_value(state: PortfolioState, marks: Mapping[str, float]) -> float:
    """Total market value of open positions marked at ``marks`` (symbol→price)."""
    total = 0.0
    for sym, pos in state.positions.items():
        if pos.is_open:
            total += pos.quantity * float(marks.get(sym, pos.entry_price))
    return total


def portfolio_equity(state: PortfolioState, marks: Mapping[str, float]) -> float:
    """Shared cash plus the marked value of all open positions."""
    return state.cash + position_value(state, marks)


def _rank_metric(trailing_returns: Sequence[float]) -> float:
    """Deterministic ranking score: cumulative trailing return over the window.

    Used only when capacity binds (more BUY signals than slots / cash). Higher =
    stronger recent move. Leakage-safe (it reads only returns through bar N).
    Returns 0.0 when the window is empty or non-finite; ties are broken by symbol
    name in the caller. This is a ``[two-way]`` policy choice (section 3.2).
    """
    if not trailing_returns:
        return 0.0
    growth = 1.0
    for r in trailing_returns:
        if not math.isfinite(r):
            return 0.0
        growth *= 1.0 + r
    return growth - 1.0


def _vol_weight(ctx: SymbolContext, config: PortfolioConfig) -> float:
    """Per-symbol target fraction of equity to deploy on a BUY.

    With vol targeting on, refuse to size on an incomplete window (return 0.0),
    mirroring the single-symbol engine. With it off, deploy the flat per-symbol
    cap. Always in ``[0, max_position_pct]`` (``compute_position_fraction`` clamps).
    """
    if config.target_vol is not None:
        if not ctx.trailing_returns:
            return 0.0  # warm-up: no full window to size against → skip
        return compute_position_fraction(
            ctx.trailing_returns, config.target_vol, config.max_position_pct
        )
    return float(config.max_position_pct)


def trailing_returns_at(
    closes: Sequence[float], i: int, vol_lookback: int
) -> tuple[float, ...]:
    """The close-to-close return window ending at bar ``i`` used for vol sizing
    and the ranking metric.

    Returns the full ``vol_lookback``-length window when available, else an empty
    tuple (warm-up: refuse to size). Reads only closes through bar ``i`` — no
    look-ahead. **Both** the backtest driver and the live runner must build
    ``SymbolContext`` through this so their sizing inputs match by construction
    ("live must equal backtested").
    """
    if i < vol_lookback or vol_lookback < 1:
        return ()
    window = closes[i - vol_lookback : i + 1]
    return tuple(
        float(window[k + 1] / window[k] - 1.0) for k in range(len(window) - 1)
    )


def build_symbol_context(
    symbol: str,
    decision: StrategyDecision,
    closes: Sequence[float],
    i: int,
    config: PortfolioConfig,
) -> SymbolContext:
    """Assemble the per-symbol decision context for bar ``i`` — the single place
    both drivers construct ``SymbolContext``, so the live runner cannot drift from
    the backtest in how it computes the close, signal, and trailing window."""
    return SymbolContext(
        symbol=symbol,
        close=float(closes[i]),
        decision=decision.action,
        reason=decision.reason,
        trailing_returns=trailing_returns_at(closes, i, config.vol_lookback),
    )


def evaluate_portfolio(
    state: PortfolioState,
    contexts: Mapping[str, SymbolContext],
    marks: Mapping[str, float],
    config: PortfolioConfig,
) -> PortfolioDecision:
    """The shared keystone: compute target orders for one decision bar.

    Both the backtest driver and the live runner call this with the same inputs
    and get the same orders — the property that keeps paper results comparable to
    the backtest. Pure: it does not mutate ``state``.

    Order of resolution (deterministic):
      1. Portfolio max-drawdown kill — if breached (and not already halted),
         flatten every open position and take no new entries this step.
      2. Per-symbol exits for held positions — stop-loss / take-profit (against
         bar-N close), then a strategy SELL. Exits run even while halted.
      3. BUY allocation for symbols that signal BUY and are not held — vol-target
         weight, ranked, greedily filled under the gross-exposure cap, the
         max-open-positions count, available shared cash, and the per-order
         notional bound. Suppressed entirely while halted.
    """
    equity = portfolio_equity(state, marks)
    gross_pct = (position_value(state, marks) / equity) if equity > 0 else 0.0

    # 1. Portfolio drawdown kill (shared check with the single-symbol engine).
    newly_halted = (
        config.max_drawdown_cutoff_pct is not None
        and not state.halted
        and check_drawdown_breach(
            state.peak_equity, equity, config.max_drawdown_cutoff_pct
        )
    )
    effective_halted = state.halted or newly_halted
    halt_reason = "portfolio max-drawdown halt"

    orders: list[TargetOrder] = []

    # 2. Exits for currently-open positions (deterministic by symbol).
    exited: set[str] = set()
    for sym in state.open_symbols():
        pos = state.positions[sym]
        ctx = contexts.get(sym)
        if effective_halted:
            orders.append(TargetOrder(sym, "SELL", 0.0, halt_reason))
            exited.add(sym)
            continue
        if ctx is None:
            # No bar this step for a held symbol: cannot evaluate an exit; hold.
            continue
        exit_sig = check_stop_target(
            pos.entry_price, ctx.close, config.stop_loss_pct, config.take_profit_pct
        )
        if exit_sig is not None:
            reason = "stop-loss" if exit_sig == ExitSignal.STOP else "take-profit"
            orders.append(TargetOrder(sym, "SELL", 0.0, reason))
            exited.add(sym)
        elif ctx.decision == StrategySignal.SELL:
            orders.append(TargetOrder(sym, "SELL", 0.0, ctx.reason))
            exited.add(sym)

    if effective_halted:
        return PortfolioDecision(
            orders=orders,
            halt_triggered=newly_halted,
            halt_reason=halt_reason if newly_halted else state.halt_reason,
            equity=equity,
            gross_exposure_pct=gross_pct,
        )

    # 3. BUY allocation. Candidates: symbols signalling BUY that are not held.
    held_after_exits = [
        s for s in state.open_symbols() if s not in exited
    ]
    slots_remaining = config.max_open_positions - len(held_after_exits)
    # Cash available now (sell proceeds settle at the same next-open and are NOT
    # counted here — conservative, and avoids spending unsettled proceeds).
    cash_remaining = state.cash
    # Gross budget left under the cap, given the positions that stay open.
    held_value = sum(
        state.positions[s].quantity * float(marks.get(s, state.positions[s].entry_price))
        for s in held_after_exits
    )
    gross_budget_remaining = config.gross_exposure_cap * equity - held_value

    candidates = [
        ctx
        for sym, ctx in contexts.items()
        if ctx.decision == StrategySignal.BUY
        and not state.positions.get(sym, PortfolioPosition(sym)).is_open
    ]
    # Deterministic ranking: strongest trailing move first, ties by symbol name.
    candidates.sort(key=lambda c: (-_rank_metric(c.trailing_returns), c.symbol))

    for ctx in candidates:
        if slots_remaining <= 0:
            break
        if cash_remaining <= 0 or gross_budget_remaining <= 0:
            break
        weight = _vol_weight(ctx, config)
        if weight <= 0.0:
            continue  # un-sizable (warm-up / un-estimable vol) → skip
        notional = weight * equity
        if config.per_order_notional_cap is not None:
            notional = min(notional, config.per_order_notional_cap)
        notional = min(notional, cash_remaining, gross_budget_remaining)
        if notional <= 0.0:
            continue
        orders.append(TargetOrder(ctx.symbol, "BUY", notional, ctx.reason))
        slots_remaining -= 1
        cash_remaining -= notional
        gross_budget_remaining -= notional

    return PortfolioDecision(
        orders=orders,
        halt_triggered=newly_halted,
        halt_reason=halt_reason if newly_halted else state.halt_reason,
        equity=equity,
        gross_exposure_pct=gross_pct,
    )


def apply_buy_fill(
    state: PortfolioState,
    symbol: str,
    ts: pd.Timestamp,
    open_price: float,
    notional: float,
    marks: Mapping[str, float],
    config: PortfolioConfig,
    reason: str = "",
) -> TradeRecord | None:
    """Fill a BUY at ``open_price`` (next-open), deploying up to ``notional`` of
    shared cash. Mutates ``state``; returns the TradeRecord, or None if nothing
    could be bought. Sizes so gross + fee never exceeds the cash budget.
    """
    fill = apply_slippage(open_price, "BUY", config.slippage_bps)
    fee_rate = config.fee_bps / 10_000.0
    budget = min(float(notional), state.cash)
    if budget <= 0.0 or fill <= 0.0:
        return None
    quantity = budget / (fill * (1.0 + fee_rate))
    if quantity <= 0.0:
        return None
    gross = quantity * fill
    fee = calculate_fee(gross, config.fee_bps)
    slip_cost = abs(fill - open_price) * quantity
    state.cash -= gross + fee
    state.positions[symbol] = PortfolioPosition(
        symbol=symbol, quantity=quantity, entry_price=fill
    )
    equity_after = portfolio_equity(state, {**marks, symbol: fill})
    return TradeRecord(
        symbol=symbol, side="BUY", timestamp=ts, price=fill, quantity=quantity,
        gross_value=gross, fee=fee, slippage=slip_cost, cash_after=state.cash,
        position_after=quantity, equity_after=equity_after, reason=reason,
    )


def apply_sell_fill(
    state: PortfolioState,
    symbol: str,
    ts: pd.Timestamp,
    raw_price: float,
    marks: Mapping[str, float],
    config: PortfolioConfig,
    reason: str,
) -> TradeRecord | None:
    """Fill a SELL of the full position at ``raw_price`` (next-open or final
    close). Mutates ``state``; returns the TradeRecord, or None if flat."""
    pos = state.positions.get(symbol)
    if pos is None or not pos.is_open:
        return None
    quantity = pos.quantity
    fill = apply_slippage(raw_price, "SELL", config.slippage_bps)
    gross = quantity * fill
    fee = calculate_fee(gross, config.fee_bps)
    slip_cost = abs(raw_price - fill) * quantity
    state.cash += gross - fee
    state.positions[symbol] = PortfolioPosition(symbol=symbol)
    equity_after = portfolio_equity(state, {**marks, symbol: fill})
    return TradeRecord(
        symbol=symbol, side="SELL", timestamp=ts, price=fill, quantity=quantity,
        gross_value=gross, fee=fee, slippage=slip_cost, cash_after=state.cash,
        position_after=0.0, equity_after=equity_after, reason=reason,
    )
