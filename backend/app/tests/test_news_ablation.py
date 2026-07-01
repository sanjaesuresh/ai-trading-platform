"""News ablation harness plumbing tests (Phase 5 M5/§6).

Per the §9 test plan: assert the price-only and price-plus-news arms produce
comparable, cost-charged outputs over the same splits; the news-aware trial count
and the paired incremental test are wired; and the LLM drag lands in the per-bar
stream charged to the news arm only. NOT a particular profitability outcome.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.ablation import run_news_ablation
from app.ml.features import FeatureLabelSpec
from app.ml.significance import paired_incremental_significance
from app.ml.training import TrainingConfig

HORIZON = 5


def _ohlcv(rows: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, rows))
    close = np.maximum(close, 1.0)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2018-01-02", periods=rows, freq="B"),
            "open": close * (1.0 + rng.normal(0, 0.002, rows)),
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": rng.integers(1_000, 5_000, rows).astype(float),
        }
    )


def _annotations(frame: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.to_datetime(frame["timestamp"]).dt.normalize()
    # Sparse news: every ~7th bar, available at that bar's close (16:00 ET).
    picks = list(range(10, len(frame), 7))
    closes = (ts.iloc[picks] + pd.Timedelta(hours=16)).dt.tz_localize("America/New_York")
    return pd.DataFrame(
        {
            "published_at": closes.dt.tz_convert("UTC").map(lambda x: x.isoformat()),
            "first_seen_at": closes.dt.tz_convert("UTC").map(lambda x: x.isoformat()),
            "sentiment": rng.uniform(-1, 1, len(picks)),
            "relevance": rng.uniform(0.5, 1.0, len(picks)),
        }
    )


def _run(cost: float, n_news_configs: int = 3):
    frames = {"SPY": _ohlcv(420, 1), "AAPL": _ohlcv(420, 2)}
    ann = {s: _annotations(f, i) for i, (s, f) in enumerate(frames.items())}
    return run_news_ablation(
        frames,
        ann,
        eval_symbol="SPY",
        annotation_cost_usd=cost,
        n_news_configs_tried=n_news_configs,
        training_config=TrainingConfig(spec=FeatureLabelSpec(horizon=HORIZON), min_selected=5),
        horizon=HORIZON,
        in_sample_dates=200,
        out_sample_dates=60,
        step_dates=60,
        mc_runs=10,
        seed=7,
    )


def test_both_arms_run_and_return_verdicts() -> None:
    result = _run(cost=50.0)
    assert result.price_arm.verdict in {"pass", "fail", "inconclusive"}
    assert result.news_arm.verdict in {"pass", "fail", "inconclusive"}
    assert result.price_arm.splits and result.news_arm.splits


def test_news_trial_count_multiplies_price_by_config_count() -> None:
    result = _run(cost=50.0, n_news_configs=4)
    assert result.news_n_trials == result.price_n_trials * 4
    assert result.news_arm.significance.n_config_trials == result.news_n_trials
    assert result.price_arm.significance.n_config_trials == result.price_n_trials


def test_llm_cost_drags_news_per_bar_stream_only() -> None:
    no_cost = _run(cost=0.0)
    with_cost = _run(cost=500.0)
    assert no_cost.daily_cost_drag == 0.0
    assert with_cost.daily_cost_drag > 0.0
    # The drag is a constant subtracted from every news bar, so the mean (news−price)
    # difference shifts down by exactly the drag — proving the cost is in the per-bar
    # stream the significance battery sees, not bolted onto the aggregate.
    assert with_cost.incremental.mean_diff == pytest.approx(
        no_cost.incremental.mean_diff - with_cost.daily_cost_drag, rel=1e-6, abs=1e-9
    )
    # Price arm is identical regardless of cost (charged to the news arm only).
    assert with_cost.price_arm.significance.sharpe == no_cost.price_arm.significance.sharpe


def test_paired_test_is_wired_and_serializable() -> None:
    result = _run(cost=50.0)
    inc = result.incremental
    assert isinstance(inc.beats_price_only, bool)
    assert inc.n_trials == result.news_n_trials
    assert result.n_paired_bars > 0
    d = result.to_dict()
    assert "incremental" in d and "price_arm" in d and "news_arm" in d
    assert d["dsr_caveat"]


def test_rejects_zero_news_configs() -> None:
    frames = {"SPY": _ohlcv(60, 1)}
    with pytest.raises(ValueError, match="n_news_configs"):
        run_news_ablation(frames, {"SPY": None}, eval_symbol="SPY", annotation_cost_usd=0.0, n_news_configs_tried=0)


# --- focused paired-bootstrap math (fast, no walk-forward) ---


def test_paired_positive_edge_detected() -> None:
    rng = np.random.default_rng(0)
    diff = rng.normal(0.01, 0.001, 300)  # clearly positive, low noise
    res = paired_incremental_significance(diff, n_trials=1, seed=1)
    assert res.mean_diff > 0
    assert res.bootstrap_p_value < 0.05


def test_paired_no_edge_not_significant() -> None:
    rng = np.random.default_rng(0)
    diff = rng.normal(0.0, 0.01, 300)  # zero-mean noise
    res = paired_incremental_significance(diff, n_trials=100, seed=1)
    assert not res.beats_price_only


def test_paired_handles_tiny_sample() -> None:
    res = paired_incremental_significance(np.array([0.01]), n_trials=1)
    assert res.n_obs == 1
    assert not res.beats_price_only
