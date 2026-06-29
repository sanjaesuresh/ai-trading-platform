"""Performance metrics from an equity curve and the list of trades.

Win rate and profit factor are computed over **round trips** (each BUY paired
with its following SELL), not over individual fills. Every metric is edge-case
safe: no trades, only winners, only losers, zero volatility, and very short
datasets must not divide by zero or raise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.backtesting.engine import EquityPoint, TradeRecord

# Daily bars assumed for annualization (Phase 1 uses daily OHLCV).
_PERIODS_PER_YEAR = 252


@dataclass
class RoundTrip:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    pnl: float
    holding_days: float


@dataclass
class Metrics:
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float  # positive magnitude, e.g. 12.5 means a -12.5% drawdown
    sharpe_ratio: float
    sortino_ratio: float
    win_rate: float  # 0..1, over round trips
    profit_factor: float
    num_round_trips: int
    num_fills: int
    avg_win: float
    avg_loss: float
    avg_holding_days: float
    exposure_pct: float  # share of bars holding a position, 0..100


def _pair_round_trips(trades: list[TradeRecord]) -> list[RoundTrip]:
    """Pair each BUY with the following SELL into a completed round trip.

    Long-only, one position at a time, so fills alternate BUY, SELL, BUY, SELL.
    PnL is net of fees: sell proceeds (gross - fee) minus buy cost (gross + fee).
    """
    round_trips: list[RoundTrip] = []
    open_buy: TradeRecord | None = None
    for trade in trades:
        if trade.side == "BUY":
            open_buy = trade
        elif trade.side == "SELL" and open_buy is not None:
            pnl = (trade.gross_value - trade.fee) - (open_buy.gross_value + open_buy.fee)
            holding = (trade.timestamp - open_buy.timestamp) / pd.Timedelta(days=1)
            round_trips.append(
                RoundTrip(
                    entry_time=open_buy.timestamp,
                    exit_time=trade.timestamp,
                    pnl=pnl,
                    holding_days=float(holding),
                )
            )
            open_buy = None
    return round_trips


def compute_metrics(
    equity_curve: list[EquityPoint],
    trades: list[TradeRecord],
    initial_capital: float,
) -> Metrics:
    equities = np.array([p.equity for p in equity_curve], dtype=float)
    n_bars = len(equities)

    final_equity = float(equities[-1]) if n_bars else float(initial_capital)
    total_return_pct = (
        (final_equity - initial_capital) / initial_capital * 100.0 if initial_capital else 0.0
    )

    # Annualized return (geometric), guarded against non-positive equity / no bars.
    if n_bars > 1 and initial_capital > 0 and final_equity > 0:
        growth = final_equity / initial_capital
        annualized_return_pct = (growth ** (_PERIODS_PER_YEAR / n_bars) - 1.0) * 100.0
    else:
        annualized_return_pct = 0.0

    # Max drawdown as a positive magnitude.
    if n_bars:
        running_peak = np.maximum.accumulate(equities)
        # running_peak is initial_capital-positive throughout, so division is safe.
        drawdowns = np.where(running_peak > 0, equities / running_peak - 1.0, 0.0)
        max_drawdown_pct = float(-drawdowns.min() * 100.0)
    else:
        max_drawdown_pct = 0.0

    # Per-bar equity returns drive Sharpe / Sortino.
    if n_bars > 1:
        bar_returns = np.diff(equities) / equities[:-1]
        bar_returns = bar_returns[np.isfinite(bar_returns)]
    else:
        bar_returns = np.array([], dtype=float)

    sharpe_ratio = _sharpe(bar_returns)
    sortino_ratio = _sortino(bar_returns)

    # Exposure: share of bars holding a position.
    if n_bars:
        held = sum(1 for p in equity_curve if p.position_value > 0)
        exposure_pct = held / n_bars * 100.0
    else:
        exposure_pct = 0.0

    # Round-trip statistics.
    round_trips = _pair_round_trips(trades)
    pnls = [rt.pnl for rt in round_trips]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    num_round_trips = len(round_trips)
    win_rate = len(wins) / num_round_trips if num_round_trips else 0.0
    gross_profit = sum(wins)
    gross_loss = -sum(losses)  # positive magnitude
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")  # winners and no losers
    else:
        profit_factor = 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    avg_holding_days = (
        float(np.mean([rt.holding_days for rt in round_trips])) if round_trips else 0.0
    )

    return Metrics(
        total_return_pct=total_return_pct,
        annualized_return_pct=annualized_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        win_rate=win_rate,
        profit_factor=profit_factor,
        num_round_trips=num_round_trips,
        num_fills=len(trades),
        avg_win=avg_win,
        avg_loss=avg_loss,
        avg_holding_days=avg_holding_days,
        exposure_pct=exposure_pct,
    )


def _sharpe(returns: np.ndarray) -> float:
    # Risk-free rate is assumed to be 0 (Phase 1). Sample std (ddof=1).
    if returns.size < 2:
        return 0.0
    std = float(returns.std(ddof=1))
    if std == 0.0:
        return 0.0
    mean = float(returns.mean())
    return mean / std * np.sqrt(_PERIODS_PER_YEAR)


def _sortino(returns: np.ndarray) -> float:
    # Downside deviation is the RMS of returns below the target (target = 0),
    # measured about 0 — NOT the std of losers about their own mean. Divided by
    # the full period count N (the classic Sortino convention). rf assumed 0.
    if returns.size < 2:
        return 0.0
    downside = returns[returns < 0]
    if downside.size == 0:
        return 0.0
    downside_dev = float(np.sqrt(np.sum(downside**2) / returns.size))
    if downside_dev == 0.0:
        return 0.0
    mean = float(returns.mean())
    return mean / downside_dev * np.sqrt(_PERIODS_PER_YEAR)
