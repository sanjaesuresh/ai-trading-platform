"""LightGBM training pipeline: determinism, fit boundaries, calibrated output."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.feature_engineering import add_technical_indicators
from app.evaluation.walk_forward import generate_purged_splits
from app.ml.features import COL_LABEL, FeatureLabelSpec, build_pooled_panel
from app.ml.training import TrainingConfig, TrainingError, train_model

HORIZON = 5


def _featured(rows: int, seed: int) -> pd.DataFrame:
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
    return add_technical_indicators(raw)


def _panel() -> pd.DataFrame:
    frames = {"SPY": _featured(500, 1), "AAPL": _featured(500, 2)}
    spec = FeatureLabelSpec(horizon=HORIZON, deadband=0.0)
    pooled, _ = build_pooled_panel(frames, spec=spec)
    return pooled


def _first_train_idx(panel: pd.DataFrame) -> np.ndarray:
    splits = generate_purged_splits(
        panel, horizon=HORIZON, in_sample_dates=300, out_sample_dates=80, step_dates=80
    )
    assert splits
    return splits[0].train_idx


def _config() -> TrainingConfig:
    return TrainingConfig(
        spec=FeatureLabelSpec(horizon=HORIZON, deadband=0.0),
        min_selected=5,
    )


def test_train_produces_calibrated_probabilities_in_range() -> None:
    panel = _panel()
    result = train_model(panel, _first_train_idx(panel), config=_config())
    cols = list(result.model.spec.feature_columns)
    proba = result.model.predict_proba_up(panel.loc[_first_train_idx(panel), cols])
    assert proba.min() >= 0.0 and proba.max() <= 1.0
    assert result.n_fit > 0 and result.n_calib > 0 and result.n_thresh > 0
    assert 0.0 <= result.model.exit_threshold <= result.model.enter_threshold <= 1.0
    assert result.model.min_hold == HORIZON


def test_training_is_deterministic_under_fixed_seed() -> None:
    panel = _panel()
    train_idx = _first_train_idx(panel)
    cols = list(_config().spec.feature_columns)
    sample = panel.loc[train_idx, cols]
    a = train_model(panel, train_idx, config=_config()).model.predict_proba_up(sample)
    b = train_model(panel, train_idx, config=_config()).model.predict_proba_up(sample)
    np.testing.assert_array_equal(a, b)


def test_training_reads_only_training_rows() -> None:
    # Vandalizing rows OUTSIDE the training window must not change the fitted model —
    # proves nothing is fit on out-of-sample data.
    panel = _panel()
    train_idx = _first_train_idx(panel)
    cols = list(_config().spec.feature_columns)
    sample = panel.loc[train_idx, cols].copy()

    base = train_model(panel, train_idx, config=_config()).model.predict_proba_up(sample)

    corrupted = panel.copy()
    outside = corrupted.index.difference(pd.Index(train_idx))
    corrupted.loc[outside, cols] = corrupted.loc[outside, cols] * 99.0 + 7.0
    corrupted.loc[outside, COL_LABEL] = 1 - corrupted.loc[outside, COL_LABEL]
    after = train_model(corrupted, train_idx, config=_config()).model.predict_proba_up(sample)

    np.testing.assert_array_equal(base, after)


def test_single_class_fit_fold_raises() -> None:
    panel = _panel()
    train_idx = _first_train_idx(panel)
    forced = panel.copy()
    forced.loc[:, COL_LABEL] = 1.0  # one class everywhere
    with pytest.raises(TrainingError):
        train_model(forced, train_idx, config=_config())


def test_empty_training_window_raises() -> None:
    panel = _panel()
    with pytest.raises(TrainingError):
        train_model(panel, np.empty(0, dtype=int), config=_config())


def test_validation_metrics_present() -> None:
    panel = _panel()
    result = train_model(panel, _first_train_idx(panel), config=_config())
    assert "auc" in result.validation_metrics
    assert "enter_threshold" in result.validation_metrics
    assert result.effective_n > 0.0
