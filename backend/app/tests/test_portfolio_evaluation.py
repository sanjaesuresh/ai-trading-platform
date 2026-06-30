"""Pure-logic tests for the portfolio walk-forward / sweep runner (Phase 3, M1).

Proves the portfolio backtest plugs into the existing honest-evaluation machinery:
splits index over the common timeline, selection is in-sample only, the chosen
combination and the rule-based baseline are scored out-of-sample, and the summary
reports out-of-sample evidence with a per-split baseline beat rate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtesting.portfolio_core import PortfolioConfig
from app.data.feature_engineering import add_technical_indicators
from app.evaluation.portfolio_runner import (
    run_portfolio_sweep,
    run_portfolio_walk_forward,
)
from app.evaluation.walk_forward import generate_splits


def _featured(seed: int, n: int = 320) -> pd.DataFrame:
    """A deterministic noisy upward series with indicators appended."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(loc=0.05, scale=1.0, size=n).cumsum()
    closes = 100.0 + steps
    closes = np.maximum(closes, 1.0)
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2021-01-04", periods=n, freq="B"),
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": rng.uniform(1_000, 5_000, size=n),
        }
    )
    return add_technical_indicators(frame)


_FRAMES = {"AAA": _featured(1), "BBB": _featured(2)}
_CONFIG = PortfolioConfig(
    initial_capital=100_000.0, fee_bps=5.0, slippage_bps=5.0,
    max_position_pct=0.5, gross_exposure_cap=1.0, max_open_positions=2,
)
_GRID = {"rsi_buy_low": [40.0, 45.0]}


def test_portfolio_sweep_runs_and_is_in_sample_only() -> None:
    results, summary = run_portfolio_sweep(
        _FRAMES, strategy_name="trend_following", param_grid=_GRID, config=_CONFIG
    )
    assert len(results) == 2  # two combinations
    assert summary.is_out_of_sample is False
    assert summary.pct_beating_baseline is None


def test_portfolio_walk_forward_produces_out_of_sample_evidence() -> None:
    n = len(set(_FRAMES["AAA"]["timestamp"]) & set(_FRAMES["BBB"]["timestamp"]))
    splits = generate_splits(
        n, scheme="rolling", in_sample_size=120, out_sample_size=60, step=60
    )
    assert splits, "expected at least one walk-forward split"

    result = run_portfolio_walk_forward(
        _FRAMES, strategy_name="trend_following", param_grid=_GRID,
        splits=splits, config=_CONFIG,
    )
    wf = result.walk_forward

    assert wf.summary is not None
    assert wf.summary.is_out_of_sample is True
    assert len(wf.splits) == len(splits)
    # Every split carries real out-of-sample and baseline metrics.
    for sr in wf.splits:
        assert sr.out_sample is not None
        assert sr.baseline_out_sample is not None
        assert sr.test_start == sr.train_end  # no gap, no overlap
        # num_trades_* is round trips (matches the single-symbol contract).
        assert sr.num_trades_out == sr.out_sample.num_round_trips
    # Beat rate is a proper fraction.
    assert 0.0 <= wf.summary.pct_beating_baseline <= 1.0

    # §6 allocator-off control: one single-position basket result per split, and
    # a proper beat-rate fraction.
    assert len(result.single_position_out_sample) == len(splits)
    assert result.pct_beating_single_position is not None
    assert 0.0 <= result.pct_beating_single_position <= 1.0
