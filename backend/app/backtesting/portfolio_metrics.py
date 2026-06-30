"""Portfolio performance metrics across multiple concurrent positions (Phase 3).

Same ``Metrics`` shape and the same edge-case discipline as the single-symbol
:mod:`app.backtesting.metrics`, so portfolio results plug into the existing
``evaluation`` reporting unchanged (it reads ``getattr(metrics, objective)``).

The only thing that differs from the single-symbol case is round-trip pairing:
a portfolio holds one long position *per symbol* concurrently, so the global
fill stream is no longer a single alternating BUY/SELL sequence. Pairing is done
**per symbol** (each symbol is itself long-only, one-position-at-a-time), then the
round trips are pooled. Equity-curve statistics (return, drawdown, Sharpe,
Sortino, exposure) are computed from the portfolio equity curve by the shared
``_equity_stats`` helper — a curve is a curve regardless of position count.
"""

from __future__ import annotations

from collections import defaultdict

from app.backtesting.metrics import (
    Metrics,
    RoundTrip,
    assemble_metrics,
    equity_stats,
    pair_round_trips,
    round_trip_stats,
)
from app.backtesting.records import EquityPoint, TradeRecord


def _pair_round_trips_by_symbol(trades: list[TradeRecord]) -> list[RoundTrip]:
    """Pair BUY→SELL round trips independently within each symbol, then pool.

    Preserves per-symbol fill order (the input order, which the driver appends in
    time order) so each symbol's stream stays a valid alternating BUY/SELL
    sequence for the single-symbol pairing routine.
    """
    by_symbol: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in trades:
        by_symbol[trade.symbol].append(trade)
    round_trips: list[RoundTrip] = []
    for symbol in sorted(by_symbol):
        round_trips.extend(pair_round_trips(by_symbol[symbol]))
    return round_trips


def compute_portfolio_metrics(
    equity_curve: list[EquityPoint],
    trades: list[TradeRecord],
    initial_capital: float,
) -> Metrics:
    """Portfolio metrics: equity stats from the curve, round trips pooled per
    symbol. Returns the same ``Metrics`` dataclass as the single-symbol path."""
    eq = equity_stats(equity_curve, initial_capital)
    rt = round_trip_stats(_pair_round_trips_by_symbol(trades))
    return assemble_metrics(eq, rt, len(trades))
