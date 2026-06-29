"""Evaluation service: size guard, strategy validation, results built from a frame.

DB-free: exercises the grid guard and the result-building seam directly with a
hand-built featured frame. Persistence is covered by the manual integration step.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.feature_engineering import add_technical_indicators
from app.schemas.evaluation import SweepRequest, WalkForwardRequest
from app.services.backtest_service import BacktestRequestError
from app.services.evaluation_service import (
    build_sweep_run,
    build_walk_forward_run,
    validate_and_expand,
)


def _featured(n: int = 160) -> pd.DataFrame:
    i = np.arange(n)
    close = 100.0 + 8.0 * np.sin(i / 3.0)
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=n, freq="D"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000.0),
        }
    )
    return add_technical_indicators(frame)


def test_grid_over_max_rejected() -> None:
    req = SweepRequest(
        symbol="OSC",
        strategy_name="trend_following",
        param_grid={"rsi_buy_low": [40.0, 45.0], "rsi_buy_high": [70.0, 75.0]},
        max_combinations=3,  # product is 4 > 3
    )
    with pytest.raises(BacktestRequestError):
        validate_and_expand(req)


def test_unknown_strategy_rejected() -> None:
    req = SweepRequest(symbol="OSC", strategy_name="nope", param_grid={"x": [1, 2]})
    with pytest.raises(BacktestRequestError):
        validate_and_expand(req)


def test_invalid_params_rejected() -> None:
    req = SweepRequest(
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid={"entry_std": [1.0], "exit_std": [2.0]},  # exit >= entry
    )
    with pytest.raises(BacktestRequestError):
        validate_and_expand(req)


def test_sweep_pipeline_builds_results_from_frame() -> None:
    req = SweepRequest(
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid={"entry_std": [1.0, 1.5]},
        initial_capital=10_000.0,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    run = build_sweep_run(req, _featured())
    assert run.kind == "sweep"
    assert run.status == "completed"
    assert run.objective == "sharpe_ratio"
    assert len(run.results["combinations"]) == 2
    assert "summary" in run.results
    # Per-combo in-sample metrics serialized to plain dicts; no out-of-sample (sweep).
    first = run.results["combinations"][0]
    assert isinstance(first["in_sample"], dict)
    assert first["out_sample"] is None


def test_walk_forward_pipeline_builds_results_from_frame() -> None:
    req = WalkForwardRequest(
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid={"entry_std": [1.0, 1.5]},
        in_sample_size=80,
        out_sample_size=40,
        step=40,
        initial_capital=10_000.0,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    run = build_walk_forward_run(req, _featured(160))
    assert run.kind == "walk_forward"
    assert len(run.results["splits"]) == 2
    split = run.results["splits"][0]
    assert isinstance(split["out_sample"], dict)
    assert isinstance(split["baseline_out_sample"], dict)
    assert "chosen_params" in split
