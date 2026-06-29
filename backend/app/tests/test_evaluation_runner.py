"""Sweep + walk-forward runners: one result per combo, per-split selection, no leakage."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.feature_engineering import add_technical_indicators
from app.evaluation.reporting import CombinationResult, select_best
from app.evaluation.runner import run_sweep, run_walk_forward
from app.evaluation.walk_forward import generate_splits

_RUN_KWARGS = {"initial_capital": 10_000.0, "fee_bps": 0.0, "slippage_bps": 0.0}


def _oscillating_frame(n: int = 200) -> pd.DataFrame:
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


def _featured(n: int = 200) -> pd.DataFrame:
    return add_technical_indicators(_oscillating_frame(n))


def test_run_sweep_returns_one_result_per_combo() -> None:
    results, summary = run_sweep(
        _featured(),
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid={"entry_std": [1.0, 1.5, 2.0]},
        run_kwargs=_RUN_KWARGS,
    )
    assert len(results) == 3
    assert all(isinstance(r, CombinationResult) for r in results)
    assert all(r.out_sample is None for r in results)  # pure sweep, no split
    assert summary.objective == "sharpe_ratio"


def test_run_sweep_respects_objective() -> None:
    results, summary = run_sweep(
        _featured(),
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid={"entry_std": [1.0, 1.5, 2.0]},
        run_kwargs=_RUN_KWARGS,
        objective="total_return_pct",
    )
    assert summary.objective == "total_return_pct"
    expected_best = max(r.in_sample.total_return_pct for r in results)
    assert summary.best == expected_best


def test_walk_forward_selects_per_split() -> None:
    splits = generate_splits(160, in_sample_size=80, out_sample_size=40, step=40)
    assert len(splits) == 2
    result = run_walk_forward(
        _featured(160),
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid={"entry_std": [1.0, 1.5]},
        splits=splits,
        run_kwargs=_RUN_KWARGS,
    )
    assert len(result.splits) == 2
    for s in result.splits:
        assert "entry_std" in s.chosen_params
        assert s.in_sample is not None and s.out_sample is not None


def test_walk_forward_no_leakage() -> None:
    # The chosen params for a split must equal select_best over train-only results.
    frame = _featured(160)
    splits = generate_splits(160, in_sample_size=80, out_sample_size=40, step=40)
    grid = {"entry_std": [1.0, 1.5]}
    result = run_walk_forward(
        frame,
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid=grid,
        splits=splits,
        run_kwargs=_RUN_KWARGS,
    )
    # Recompute the in-sample selection independently for the first split.
    from app.backtesting.engine import run_backtest
    from app.backtesting.metrics import compute_metrics
    from app.strategies.registry import resolve_strategy

    sp = splits[0]
    train = frame.iloc[sp.train_start : sp.train_end].reset_index(drop=True)
    train_results = []
    for entry_std in [1.0, 1.5]:
        strat = resolve_strategy("mean_reversion", {"entry_std": entry_std})
        r = run_backtest(train, strat, symbol="OSC", **_RUN_KWARGS)
        m = compute_metrics(r.equity_curve, r.trades, _RUN_KWARGS["initial_capital"])
        train_results.append(
            CombinationResult(
                params={"entry_std": entry_std},
                in_sample=m,
                out_sample=None,
                num_trades_in=m.num_round_trips,
                num_trades_out=0,
            )
        )
    expected = select_best(train_results, objective="sharpe_ratio")
    assert result.splits[0].chosen_params == expected.params


def test_walk_forward_includes_baseline_out_sample() -> None:
    splits = generate_splits(160, in_sample_size=80, out_sample_size=40, step=40)
    result = run_walk_forward(
        _featured(160),
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid={"entry_std": [1.0, 1.5]},
        splits=splits,
        run_kwargs=_RUN_KWARGS,
        baseline_strategy_name="trend_following",
    )
    for s in result.splits:
        # Baseline ran over the same test slice; it is a real Metrics record.
        assert s.baseline_out_sample is not None
        assert hasattr(s.baseline_out_sample, "sharpe_ratio")


def test_walk_forward_empty_splits() -> None:
    result = run_walk_forward(
        _featured(160),
        symbol="OSC",
        strategy_name="mean_reversion",
        param_grid={"entry_std": [1.0, 1.5]},
        splits=[],
        run_kwargs=_RUN_KWARGS,
    )
    assert result.splits == []
    assert result.summary is not None
    assert result.summary.best == 0.0 and result.summary.worst == 0.0
