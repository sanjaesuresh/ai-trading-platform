"""Multi-symbol portfolio backtest driver (Phase 3, M1).

Drives the shared :mod:`app.backtesting.portfolio_core` over stored daily history
for a basket of symbols and produces a portfolio equity curve and trade list. It
is the *validation path* for the live allocator: because it shares the core with
the live runner, a backtest of a deployment's config reproduces exactly the
allocation / risk logic that will run live.

Timeline alignment
------------------
Symbols are aligned on the **intersection** of their timestamps — the common
trading days on which every basket symbol has a bar. US equities on the same
exchange calendar (SPY, AAPL, …) share their trading days, so the intersection is
the natural common clock and keeps the loop in lockstep with a shared cash pool.
Days where any symbol is missing a bar are dropped (and logged), so the backtest
never trades on a day it lacks a price for.

Execution model (unchanged in shape from Phase 1/2, now portfolio-wide)
----------------------------------------------------------------------
- Strategy decisions are taken at bar N's close; the resulting orders fill at bar
  N+1's open with fees and slippage. No look-ahead.
- The portfolio drawdown kill is checked against equity marked to bar N's close.
- Every position still open on the final bar is force-closed at that bar's close.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from app.backtesting.portfolio_core import (
    EquityPoint,
    PortfolioConfig,
    PortfolioPosition,
    PortfolioState,
    SymbolContext,
    TradeRecord,
    apply_buy_fill,
    apply_sell_fill,
    build_symbol_context,
    evaluate_portfolio,
    portfolio_equity,
)
from app.strategies.base_strategy import BaseStrategy, Position

log = logging.getLogger(__name__)

# What the driver accepts for "the strategy": either one shared instance (the
# original contract, kept for the stateless rule strategies and every existing
# caller), a per-symbol mapping of instances, or a factory that builds a fresh
# instance for a given symbol. The latter two give a stateful strategy (e.g. the
# ML classifier, which carries ``_bars_held``) an ISOLATED instance per symbol so
# one symbol's holding counter cannot bleed into another's signal.
StrategyResolvable = (
    BaseStrategy | Mapping[str, BaseStrategy] | Callable[[str], BaseStrategy]
)


@dataclass
class PortfolioBacktestResult:
    symbols: list[str]
    strategy_name: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    halted: bool = False
    halt_timestamp: pd.Timestamp | None = None


def align_frames(
    frames: Mapping[str, pd.DataFrame],
) -> tuple[list[str], list[pd.Timestamp], dict[str, pd.DataFrame]]:
    """Align every symbol's frame to the common (intersection) timestamps.

    Returns the sorted symbol list, the common timeline, and per-symbol frames
    re-indexed (timestamp as index) to that timeline, so ``.iloc[i]`` refers to
    the same date for all. Shared with the walk-forward runner, which slices the
    aligned frames by split bar-index so every symbol is sliced on one clock.
    """
    symbols = sorted(frames)
    common: set[pd.Timestamp] | None = None
    for sym in symbols:
        ts = {pd.Timestamp(t) for t in frames[sym]["timestamp"]}
        common = ts if common is None else (common & ts)
    timeline = sorted(common) if common else []

    aligned: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        f = frames[sym].copy()
        f["timestamp"] = [pd.Timestamp(t) for t in f["timestamp"]]
        f = f.set_index("timestamp").reindex(timeline)
        aligned[sym] = f
    return symbols, timeline, aligned


def _resolve_strategies(
    strategy: StrategyResolvable, symbols: Sequence[str]
) -> dict[str, BaseStrategy]:
    """Resolve ``strategy`` into one ``BaseStrategy`` instance per symbol.

    - A single ``BaseStrategy`` is shared across every symbol — the original
      behaviour, exact and unchanged, which is correct for the stateless rule
      strategies and every pre-existing caller.
    - A ``Mapping[str, BaseStrategy]`` supplies an explicit instance per symbol;
      every walked symbol must have one.
    - A ``Callable[[str], BaseStrategy]`` is a factory invoked once per symbol.

    The mapping/factory paths give a single-run *stateful* strategy (the ML
    classifier carries ``self._bars_held``) an isolated instance per symbol, so a
    held symbol's bar counter cannot corrupt another symbol's signal.
    """
    if isinstance(strategy, BaseStrategy):
        return dict.fromkeys(symbols, strategy)
    if isinstance(strategy, Mapping):
        missing = [s for s in symbols if s not in strategy]
        if missing:
            raise ValueError(
                "Per-symbol strategy mapping is missing instance(s) for: "
                f"{', '.join(missing)}."
            )
        return {s: strategy[s] for s in symbols}
    if callable(strategy):
        return {s: strategy(s) for s in symbols}
    raise TypeError(
        "strategy must be a BaseStrategy, a Mapping[str, BaseStrategy], or a "
        f"Callable[[str], BaseStrategy]; got {type(strategy).__name__}."
    )


def run_portfolio_backtest(
    frames: Mapping[str, pd.DataFrame],
    strategy: StrategyResolvable,
    config: PortfolioConfig,
) -> PortfolioBacktestResult:
    """Walk the common timeline and produce the portfolio equity curve + trades.

    ``frames`` maps each symbol to its featured OHLCV frame (indicators already
    appended). ``strategy`` is either one shared instance applied to every symbol
    (the original contract, fine for the stateless rule strategies) or — for a
    stateful strategy like the ML classifier — a per-symbol mapping or factory so
    each symbol decides on its own isolated instance (see ``_resolve_strategies``).
    ``config`` holds capital, costs, sizing, and the portfolio risk limits.
    """
    symbols, timeline, aligned = align_frames(frames)
    strategies = _resolve_strategies(strategy, symbols)
    n = len(timeline)
    state = PortfolioState(
        cash=float(config.initial_capital),
        peak_equity=float(config.initial_capital),
        positions={s: PortfolioPosition(symbol=s) for s in symbols},
    )

    # Per-symbol close series for the trailing vol/rank window (common timeline).
    closes = {s: aligned[s]["close"].to_numpy(dtype=float).tolist() for s in symbols}

    pending: list = []  # list[TargetOrder] to fill at the next bar's open
    trades: list[TradeRecord] = []
    equity_curve: list[EquityPoint] = []

    for i in range(n):
        ts = timeline[i]
        is_final = i == n - 1
        opens = {s: float(aligned[s]["open"].iloc[i]) for s in symbols}
        marks_close = {s: float(aligned[s]["close"].iloc[i]) for s in symbols}

        # 1. Fill orders decided on the previous bar, at this bar's open.
        #    SELLs first (free cash), then BUYs (already budgeted against pre-sell
        #    cash, so order does not change affordability — see core §3).
        for order in [o for o in pending if o.side == "SELL"]:
            rec = apply_sell_fill(
                state, order.symbol, ts, opens[order.symbol], opens, config,
                order.reason,
            )
            if rec is not None:
                trades.append(rec)
        for order in [o for o in pending if o.side == "BUY"]:
            rec = apply_buy_fill(
                state, order.symbol, ts, opens[order.symbol], order.notional,
                opens, config, order.reason,
            )
            if rec is not None:
                trades.append(rec)
        pending = []

        # 2. Force-close every open position on the final bar (no next open).
        if is_final:
            for sym in state.open_symbols():
                rec = apply_sell_fill(
                    state, sym, ts, marks_close[sym], marks_close, config,
                    "Force-close open position on final bar.",
                )
                if rec is not None:
                    trades.append(rec)

        # 3. Mark portfolio equity to this bar's close.
        equity = portfolio_equity(state, marks_close)
        pos_value = equity - state.cash
        equity_curve.append(
            EquityPoint(timestamp=ts, equity=equity, cash=state.cash,
                        position_value=pos_value)
        )
        if equity > state.peak_equity:
            state.peak_equity = equity

        # 4. Decide for the next bar (the final bar has no next open to fill on).
        if is_final:
            continue

        contexts: dict[str, SymbolContext] = {}
        for sym in symbols:
            row = aligned[sym].iloc[i]
            if pd.isna(row.get("open")) or pd.isna(row.get("close")):
                continue
            pos = state.positions[sym]
            decision = strategies[sym].generate_signal(
                row, Position(quantity=pos.quantity, entry_price=pos.entry_price)
            )
            # Built through the core's shared helper so the live runner (M3)
            # constructs identical context (close, signal, trailing window).
            contexts[sym] = build_symbol_context(
                sym, decision, closes[sym], i, config
            )

        portfolio_decision = evaluate_portfolio(state, contexts, marks_close, config)
        if portfolio_decision.halt_triggered and not state.halted:
            state.halted = True
            state.halt_reason = portfolio_decision.halt_reason
            log.info(
                "Portfolio max-drawdown kill tripped at %s; new entries suppressed "
                "for the rest of this run.",
                ts,
            )
        pending = portfolio_decision.orders

    final_equity = equity_curve[-1].equity if equity_curve else float(config.initial_capital)
    total_return_pct = (
        (final_equity - config.initial_capital) / config.initial_capital * 100.0
        if config.initial_capital
        else 0.0
    )
    halt_ts = None
    # The halt timestamp is the close bar at which the kill first tripped; recover
    # it from the first flatten trade tagged with the halt reason, if any.
    if state.halted:
        for rec in trades:
            if rec.reason == "portfolio max-drawdown halt":
                # The flatten fills at the open *after* the trip; the trip bar is
                # the prior close. We report the fill bar for auditability.
                halt_ts = rec.timestamp
                break

    # Every per-symbol instance is the same strategy type, so any one names the
    # run; for the shared-instance path that is exactly the prior ``strategy.name``.
    strategy_name = (
        strategy.name
        if isinstance(strategy, BaseStrategy)
        else (next(iter(strategies.values())).name if strategies else "portfolio")
    )
    return PortfolioBacktestResult(
        symbols=symbols,
        strategy_name=strategy_name,
        initial_capital=float(config.initial_capital),
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        equity_curve=equity_curve,
        trades=trades,
        halted=state.halted,
        halt_timestamp=halt_ts,
    )
