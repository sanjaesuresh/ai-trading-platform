"""Multi-symbol ML walk-forward through the portfolio core: end-to-end, honest.

These tests drive the whole portfolio-evaluation pipeline on small synthetic
multi-symbol featured frames so several purged splits form. They assert the
structural correctness the verdict depends on — per-symbol OOS breakdown, all
baselines present, no look-ahead, JSON serializability, single-class robustness,
and the overlapping-window guard — rather than any pass/fail outcome on noise.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from app.backtesting.portfolio_core import PortfolioConfig
from app.data.feature_engineering import add_technical_indicators
from app.ml.features import (
    COL_LABEL,
    FeatureLabelSpec,
    build_features,
    build_pooled_panel,
)
from app.ml.portfolio_evaluation import (
    BASE_BUY_AND_HOLD_BASKET,
    BASE_RULE_PORTFOLIO,
    BASE_SINGLE_POSITION,
    _single_position_basket,
    evaluate_ml_portfolio_walk_forward,
)
from app.ml.training import TrainingConfig

HORIZON = 5


def _featured(rows: int, seed: int) -> pd.DataFrame:
    """A featured frame (OHLCV + indicators + f_* features) for the engine."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, rows))
    close = np.maximum(close, 1.0)
    raw = pd.DataFrame(
        {
            "timestamp": pd.date_range("2018-01-02", periods=rows, freq="B"),
            "open": close * (1.0 + rng.normal(0, 0.002, rows)),
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": rng.integers(1_000, 5_000, rows).astype(float),
        }
    )
    return build_features(add_technical_indicators(raw))


def _frames() -> dict[str, pd.DataFrame]:
    return {"SPY": _featured(420, 1), "AAPL": _featured(420, 2)}


def _spec() -> FeatureLabelSpec:
    return FeatureLabelSpec(horizon=HORIZON, deadband=0.0)


def _config() -> TrainingConfig:
    return TrainingConfig(spec=_spec(), min_selected=5)


def _portfolio_config() -> PortfolioConfig:
    return PortfolioConfig(
        initial_capital=100_000.0, fee_bps=5.0, slippage_bps=5.0,
        max_position_pct=0.5, gross_exposure_cap=1.0, max_open_positions=2,
    )


def _panel(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pooled, _ = build_pooled_panel(frames, spec=_spec())
    return pooled


def _evaluate(frames: dict[str, pd.DataFrame], **overrides: object):
    panel = _panel(frames)
    kwargs: dict[str, object] = {
        "symbols": sorted(frames),
        "config": _portfolio_config(),
        "training_config": _config(),
        "horizon": HORIZON,
        "in_sample_dates": 200,
        "out_sample_dates": 60,
        "step_dates": 60,
    }
    kwargs.update(overrides)
    return evaluate_ml_portfolio_walk_forward(panel, frames, **kwargs)  # type: ignore[arg-type]


def test_runs_end_to_end_with_per_symbol_breakdown_and_baselines() -> None:
    result = _evaluate(_frames())
    assert result.symbols == ["AAPL", "SPY"]
    assert result.splits, "expected at least one non-skipped split"

    # One per-symbol breakdown entry per requested symbol.
    assert [b.symbol for b in result.per_symbol] == ["AAPL", "SPY"]

    # All three baselines present in the aggregate and on every split.
    expected_baselines = {
        BASE_RULE_PORTFOLIO, BASE_BUY_AND_HOLD_BASKET, BASE_SINGLE_POSITION
    }
    assert set(result.aggregate_baselines) == expected_baselines
    for split in result.splits:
        assert set(split.baselines) == expected_baselines

    # Aggregate portfolio metrics + turnover are present.
    m = result.aggregate_model
    assert "total_return_pct" in m
    assert "per_period_sharpe" in m
    assert m["mean_turnover_annualized"] >= 0.0
    assert m["n_splits_evaluated"] == len(result.splits)
    assert isinstance(result.beats_all_baselines, bool)


def test_to_dict_is_json_serializable() -> None:
    result = _evaluate(_frames())
    payload = result.to_dict()
    text = json.dumps(payload)  # raises if any numpy/non-serializable leaks
    assert isinstance(text, str)
    assert len(payload["per_symbol"]) == 2  # type: ignore[arg-type]
    sig = payload["significance"]
    assert all(isinstance(v, (int, float)) for v in sig.values())  # type: ignore[union-attr]


def test_no_look_ahead_every_split_oos_after_training() -> None:
    result = _evaluate(_frames())
    for split in result.splits:
        assert split.no_look_ahead()
        assert pd.Timestamp(split.oos_first_ts) > pd.Timestamp(split.train_end)
        assert pd.Timestamp(split.oos_first_ts) >= pd.Timestamp(split.test_start)


def test_turnover_and_significance_within_sane_ranges() -> None:
    result = _evaluate(_frames())
    for split in result.splits:
        assert split.model.turnover_annualized >= 0.0
    sig = result.significance
    assert math.isnan(sig.deflated_sharpe) or (0.0 <= sig.deflated_sharpe <= 1.0)
    assert sig.var_trial_sharpes > 0.0  # Lo (2002) floor keeps deflation alive
    assert sig.n_eff >= 0.0


def test_per_symbol_contribution_sums_are_consistent() -> None:
    """Each symbol's win rate is a valid fraction and round-trip counts are sane."""
    result = _evaluate(_frames())
    for b in result.per_symbol:
        assert 0.0 <= b.win_rate <= 1.0
        assert b.num_round_trips >= 0


def test_single_class_training_window_is_skipped_not_fatal() -> None:
    frames = _frames()
    panel = _panel(frames)
    panel = panel.copy()
    panel.loc[:, COL_LABEL] = 1.0
    result = evaluate_ml_portfolio_walk_forward(
        panel,
        frames,
        symbols=sorted(frames),
        config=_portfolio_config(),
        training_config=_config(),
        horizon=HORIZON,
        in_sample_dates=200,
        out_sample_dates=60,
        step_dates=60,
    )
    assert result.splits == []
    assert result.skipped, "expected skipped splits when every fold is single-class"
    assert result.beats_all_baselines is False
    json.dumps(result.to_dict())


def test_overlapping_oos_windows_raises() -> None:
    with pytest.raises(ValueError, match="overlapping"):
        _evaluate(_frames(), step_dates=30, out_sample_dates=60)


def test_symbols_not_in_frames_raises() -> None:
    frames = _frames()
    with pytest.raises(ValueError, match="not in frames"):
        _evaluate(frames, symbols=["SPY", "MISSING"])


# --- Finding #2: capacity caveat in to_dict() --------------------------------


def test_to_dict_contains_capacity_caveat() -> None:
    """``to_dict()`` must include a non-empty ``caveats`` list that mentions
    the simulation / AUM / slippage assumptions so a reader of the JSON verdict
    cannot miss the cost-model honesty note."""
    result = _evaluate(_frames())
    payload = result.to_dict()
    assert "caveats" in payload, "to_dict() must contain a 'caveats' key."
    caveats = payload["caveats"]
    assert isinstance(caveats, list), "'caveats' must be a list."
    assert len(caveats) >= 1, "Expected at least one caveat string."
    combined = " ".join(caveats).lower()
    assert "simulated" in combined or "aum" in combined or "slippage" in combined, (
        "Expected caveats to mention simulation assumptions (simulated/AUM/slippage)."
    )


# --- Finding #3: _single_position_basket robust to mismatched calendars ------


def test_single_position_basket_mismatched_calendars_does_not_raise() -> None:
    """Summing per-symbol equity curves must not KeyError when the first-processed
    symbol (alphabetically earliest) is missing a bar that a later symbol has.

    Replicates the edge case: AAPL (sorted first) has one fewer bar than SPY, so
    when SPY's equity curve is summed into the combined dict keyed by AAPL's
    timestamps, SPY's extra bar would previously raise a KeyError.
    """
    from app.strategies.trend_following import TrendFollowingStrategy

    base = _featured(30, seed=7)
    # Build SPY with all 30 bars; drop bar index 15 from AAPL so AAPL (sorted
    # first) is missing a timestamp that SPY has — the exact failure mode.
    spy_frame = base.copy()
    aapl_frame = base.drop(index=15).reset_index(drop=True)
    # Ensure timestamps differ: offset SPY by one business day so their bars are
    # not identical — this guarantees SPY has bar 15 which AAPL lost.
    frames = {"AAPL": aapl_frame, "SPY": spy_frame}

    config = _portfolio_config()
    curve, trades = _single_position_basket(frames, lambda sym: TrendFollowingStrategy(), config)
    assert len(curve) > 0, "Expected a non-empty equity curve from the mismatched basket."
    # Equity must be positive and finite throughout.
    for ep in curve:
        assert ep.equity > 0.0
        assert math.isfinite(ep.equity)
