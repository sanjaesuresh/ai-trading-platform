"""Walk-forward train-then-test evaluation: end-to-end, no-look-ahead, baselines.

These tests drive the whole verdict pipeline on small synthetic multi-symbol
frames so several purged splits form. They assert the structural correctness the
verdict depends on (no look-ahead, all baselines present, valid statistic ranges,
JSON serializability, single-class robustness) rather than any particular pass/fail
outcome on noise data.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from app.data.feature_engineering import add_technical_indicators
from app.ml.evaluation import (
    BASE_BUY_AND_HOLD,
    BASE_LOGISTIC,
    BASE_RULE,
    default_n_config_trials,
    evaluate_ml_walk_forward,
)
from app.ml.features import (
    COL_LABEL,
    FeatureLabelSpec,
    build_features,
    build_pooled_panel,
)
from app.ml.training import TrainingConfig

HORIZON = 5


def _featured(rows: int, seed: int) -> pd.DataFrame:
    """A featured frame (OHLCV + indicators + f_* features), mirroring the training
    test helper but with build_features appended for the engine."""
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


def _panel(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pooled, _ = build_pooled_panel(frames, spec=_spec())
    return pooled


def _evaluate(frames: dict[str, pd.DataFrame], **overrides: object):
    panel = _panel(frames)
    kwargs: dict[str, object] = {
        "eval_symbol": "SPY",
        "training_config": _config(),
        "horizon": HORIZON,
        "in_sample_dates": 200,
        "out_sample_dates": 60,
        "step_dates": 60,
        "mc_runs": 25,
        "seed": 7,
    }
    kwargs.update(overrides)
    return evaluate_ml_walk_forward(panel, frames, **kwargs)  # type: ignore[arg-type]


def test_runs_end_to_end_and_returns_a_verdict() -> None:
    result = _evaluate(_frames())
    assert result.eval_symbol == "SPY"
    assert result.verdict in {"pass", "fail", "inconclusive"}
    assert result.splits, "expected at least one non-skipped split"
    assert result.reasons


def test_no_look_ahead_every_oos_bar_after_training_end() -> None:
    result = _evaluate(_frames())
    for split in result.splits:
        assert split.no_look_ahead()
        assert pd.Timestamp(split.oos_first_ts) > pd.Timestamp(split.train_end)
        assert pd.Timestamp(split.oos_first_ts) >= pd.Timestamp(split.test_start)


def test_all_four_baselines_present_every_split() -> None:
    result = _evaluate(_frames())
    for split in result.splits:
        assert set(split.baselines) == {BASE_BUY_AND_HOLD, BASE_RULE, BASE_LOGISTIC}
        # The Monte-Carlo ensemble (the fourth baseline) lives at split level.
        assert len(split.mc_returns) == 25
    assert BASE_BUY_AND_HOLD in result.aggregate_baselines
    assert BASE_RULE in result.aggregate_baselines
    assert BASE_LOGISTIC in result.aggregate_baselines


def test_to_dict_is_json_serializable_no_numpy_leaks() -> None:
    result = _evaluate(_frames())
    payload = result.to_dict()
    text = json.dumps(payload)  # raises if any numpy scalar or non-serializable leaks
    assert isinstance(text, str)
    # Spot-check no numpy types survived into the tree.
    sig = payload["significance"]
    assert all(isinstance(v, (int, float, str)) for v in sig.values())  # type: ignore[union-attr]


def test_turnover_present_and_non_negative_on_model() -> None:
    result = _evaluate(_frames())
    for split in result.splits:
        assert split.model.turnover_annualized >= 0.0
    assert result.aggregate_model["mean_turnover_annualized"] >= 0.0


def test_statistics_within_valid_ranges() -> None:
    result = _evaluate(_frames())
    sig = result.significance
    for stat in (sig.deflated_sharpe, sig.pbo, sig.mc_percentile):
        assert math.isnan(stat) or (0.0 <= stat <= 1.0)
    assert sig.n_eff >= 0.0
    assert sig.n_config_trials == default_n_config_trials(_config())


def test_single_class_training_window_is_skipped_not_fatal() -> None:
    # Force every label to one class: every model fit fold is single-class, so every
    # split must be recorded as skipped and the run must still complete with a verdict.
    frames = _frames()
    panel = _panel(frames)
    panel = panel.copy()
    panel.loc[:, COL_LABEL] = 1.0
    result = evaluate_ml_walk_forward(
        panel,
        frames,
        eval_symbol="SPY",
        training_config=_config(),
        horizon=HORIZON,
        in_sample_dates=200,
        out_sample_dates=60,
        step_dates=60,
        mc_runs=10,
        seed=7,
    )
    assert result.splits == []
    assert result.skipped, "expected skipped splits when every fold is single-class"
    assert result.verdict == "inconclusive"
    json.dumps(result.to_dict())


def test_logistic_floor_scaler_fit_on_training_only() -> None:
    # The logistic floor's StandardScaler must be fit on the training fold only —
    # corrupting rows OUTSIDE the training window must not change its fitted means.
    from app.evaluation.walk_forward import generate_purged_splits
    from app.ml.evaluation import _logistic_factory
    from app.ml.training import train_model

    frames = _frames()
    panel = _panel(frames)
    splits = generate_purged_splits(
        panel, horizon=HORIZON, in_sample_dates=200, out_sample_dates=60, step_dates=60
    )
    assert splits
    train_idx = splits[0].train_idx
    feat_cols = list(_config().spec.feature_columns)
    log_config = TrainingConfig(
        spec=_spec(),
        min_selected=5,
        calibration="none",
        estimator_factory=_logistic_factory,
    )

    before = train_model(panel, train_idx, config=log_config)
    means_before = before.model.classifier.named_steps["scaler"].mean_.copy()

    corrupted = panel.copy()
    outside = corrupted.index.difference(pd.Index(train_idx))
    corrupted.loc[outside, feat_cols] = corrupted.loc[outside, feat_cols] * 99.0 + 7.0
    corrupted.loc[outside, COL_LABEL] = 1 - corrupted.loc[outside, COL_LABEL]
    after = train_model(corrupted, train_idx, config=log_config)
    means_after = after.model.classifier.named_steps["scaler"].mean_

    np.testing.assert_array_equal(means_before, means_after)
    # And the wrapped classifier really is the scaler+logistic pipeline (calib off).
    assert before.model.classifier.named_steps["clf"].__class__.__name__ == (
        "LogisticRegression"
    )


def test_classification_metrics_present_or_nan() -> None:
    result = _evaluate(_frames())
    for split in result.splits:
        assert "auc" in split.classification
        assert "brier" in split.classification
        auc = split.classification["auc"]
        assert math.isnan(auc) or (0.0 <= auc <= 1.0)


@pytest.mark.parametrize("override", [{"n_config_trials": 999}])
def test_caller_can_override_trial_count(override: dict[str, object]) -> None:
    result = _evaluate(_frames(), **override)
    assert result.significance.n_config_trials == 999
