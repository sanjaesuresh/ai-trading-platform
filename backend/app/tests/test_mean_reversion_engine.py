"""Mean-reversion through the engine: same execution path, M4 risk/sizing intact.

Confirms the second strategy plugs into the existing engine — next-bar-open fills,
round-trip metrics, and the M4 sizing/stop path all work unchanged. DB-free.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.backtesting.engine import run_backtest
from app.backtesting.metrics import compute_metrics
from app.data.feature_engineering import add_technical_indicators
from app.strategies.mean_reversion import MeanReversionStrategy


def _oscillating_frame(n: int = 90) -> pd.DataFrame:
    """Deterministic oscillation so dips fall below the band and recover above it."""
    i = np.arange(n)
    close = 100.0 + 8.0 * np.sin(i / 3.0)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=n, freq="D"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000.0),
        }
    )


def test_mean_reversion_produces_trades() -> None:
    featured = add_technical_indicators(_oscillating_frame())
    result = run_backtest(
        featured,
        MeanReversionStrategy(entry_std=1.0, exit_std=0.0),
        "OSC",
        initial_capital=10_000.0,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    assert result.strategy_name == "mean_reversion"
    assert len(result.trades) >= 2  # at least one round trip


def test_buy_fills_at_next_bar_open() -> None:
    featured = add_technical_indicators(_oscillating_frame())
    result = run_backtest(
        featured,
        MeanReversionStrategy(entry_std=1.0, exit_std=0.0),
        "OSC",
        initial_capital=10_000.0,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    open_by_ts = dict(zip(featured["timestamp"], featured["open"], strict=True))
    buys = [t for t in result.trades if t.side == "BUY"]
    assert buys, "expected at least one buy fill"
    for buy in buys:
        # Zero slippage → the fill price is exactly the bar's open it filled on.
        assert buy.price == open_by_ts[buy.timestamp]


def test_round_trip_metrics_shape() -> None:
    featured = add_technical_indicators(_oscillating_frame())
    result = run_backtest(
        featured,
        MeanReversionStrategy(entry_std=1.0, exit_std=0.0),
        "OSC",
        initial_capital=10_000.0,
    )
    metrics = compute_metrics(result.equity_curve, result.trades, 10_000.0)
    assert metrics.num_fills == len(result.trades)
    assert metrics.num_round_trips >= 1
    assert math.isfinite(metrics.win_rate)


def test_mean_reversion_with_sizing_and_stop_routes_cleanly() -> None:
    # M4 interaction: sizing + stop-loss on a non-trend-following strategy.
    featured = add_technical_indicators(_oscillating_frame())
    result = run_backtest(
        featured,
        MeanReversionStrategy(entry_std=1.0, exit_std=0.0),
        "OSC",
        initial_capital=10_000.0,
        fee_bps=5.0,
        slippage_bps=5.0,
        target_vol=0.15,
        vol_lookback=20,
        stop_loss_pct=0.05,
    )
    assert math.isfinite(result.final_equity)
    metrics = compute_metrics(result.equity_curve, result.trades, 10_000.0)
    assert metrics.num_fills == len(result.trades)
    # Force-close guarantees no dangling position at the end.
    assert result.trades[-1].position_after == 0.0 if result.trades else True
