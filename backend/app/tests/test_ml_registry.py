"""Model registry: artifact round-trip, reproducible metadata, spec guard."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.feature_engineering import add_technical_indicators
from app.evaluation.walk_forward import generate_purged_splits
from app.ml.features import FeatureLabelSpec, build_pooled_panel
from app.ml.model import TrainedModel
from app.ml.registry import (
    CodeVersion,
    assert_live_spec,
    list_models,
    load_metadata,
    load_model,
    save_model,
)
from app.ml.training import TrainingConfig, train_model

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


def _train(config: TrainingConfig):
    frames = {"SPY": _featured(500, 1), "AAPL": _featured(500, 2)}
    panel, _ = build_pooled_panel(frames, spec=config.spec)
    splits = generate_purged_splits(
        panel, horizon=HORIZON, in_sample_dates=300, out_sample_dates=80, step_dates=80
    )
    result = train_model(panel, splits[0].train_idx, config=config)
    return result, panel


def _config() -> TrainingConfig:
    return TrainingConfig(spec=FeatureLabelSpec(horizon=HORIZON, deadband=0.0), min_selected=5)


def test_artifact_round_trips_to_identical_predictions(tmp_path) -> None:
    config = _config()
    result, panel = _train(config)
    meta = save_model(result, symbols=["SPY", "AAPL"], config=config, model_dir=tmp_path)

    loaded = load_model(meta.model_id, tmp_path)
    cols = list(config.spec.feature_columns)
    sample = panel.loc[:200, cols]
    np.testing.assert_array_equal(
        result.model.predict_proba_up(sample), loaded.predict_proba_up(sample)
    )


def test_metadata_reproduces_configuration(tmp_path) -> None:
    config = _config()
    result, _ = _train(config)
    meta = save_model(result, symbols=["SPY", "AAPL"], config=config, model_dir=tmp_path)

    on_disk = load_metadata(meta.model_id, tmp_path)
    assert on_disk.feature_spec_version == config.spec.version
    assert on_disk.horizon == HORIZON
    assert on_disk.seed == config.seed
    assert on_disk.num_threads == config.num_threads
    assert on_disk.lgbm_params == dict(config.lgbm_params)
    assert on_disk.symbols == ["SPY", "AAPL"]
    assert on_disk.enter_threshold == result.model.enter_threshold
    assert on_disk.artifact_hash and len(on_disk.artifact_hash) == 64
    assert "auc" in on_disk.validation_metrics


def test_dirty_tree_state_is_recorded(tmp_path) -> None:
    config = _config()
    result, _ = _train(config)
    cv = CodeVersion(git_hash="abc123", dirty=True, diff_hash="deadbeef")
    meta = save_model(
        result, symbols=["SPY"], config=config, model_dir=tmp_path, code_version=cv
    )
    on_disk = load_metadata(meta.model_id, tmp_path)
    assert on_disk.code_git_hash == "abc123"
    assert on_disk.code_dirty is True
    assert on_disk.code_diff_hash == "deadbeef"


def test_list_models_returns_registered(tmp_path) -> None:
    config = _config()
    result, _ = _train(config)
    save_model(result, symbols=["SPY"], config=config, model_dir=tmp_path)
    metas = list_models(tmp_path)
    assert len(metas) == 1


def test_load_missing_model_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_model("nonexistent", tmp_path)


def test_assert_live_spec_rejects_stale_spec() -> None:
    stale = TrainedModel(
        classifier=object(),
        spec=FeatureLabelSpec(version="v0-old"),
        enter_threshold=0.5,
        exit_threshold=0.45,
        min_hold=5,
        calibrated=False,
    )
    with pytest.raises(ValueError, match="feature-spec"):
        assert_live_spec(stale)
