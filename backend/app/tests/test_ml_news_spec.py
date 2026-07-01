"""Feature-spec version authority tests (Phase 5 M5/§3).

Two directions, per the §9 test plan:
- a price-plus-news model with a stale NEWS version is refused;
- an old price-only model still fails when the live PRICE version is bumped
  (the Phase 4 check did not regress).
"""

from __future__ import annotations

import pytest

from app.ml import features as features_mod
from app.ml import news_features as news_mod
from app.ml import registry
from app.ml.features import FEATURE_COLUMNS


def _model(spec):
    from app.ml.model import TrainedModel

    return TrainedModel(
        classifier=object(),
        spec=spec,
        enter_threshold=0.5,
        exit_threshold=0.45,
        min_hold=5,
        calibrated=False,
    )


def test_live_versions_read_both_components() -> None:
    live = registry.live_feature_versions()
    assert live["price"] == features_mod.FEATURE_SPEC_VERSION
    assert live["news"] == news_mod.NEWS_FEATURE_SPEC_VERSION


def test_price_only_model_passes_live() -> None:
    from app.ml.features import FeatureLabelSpec

    registry.assert_live_spec(_model(FeatureLabelSpec()))  # current price-only spec


def test_price_only_model_fails_when_price_version_bumped(monkeypatch) -> None:
    from app.ml.features import FeatureLabelSpec

    model = _model(FeatureLabelSpec())  # carries the current price version
    monkeypatch.setattr(features_mod, "FEATURE_SPEC_VERSION", "v999-new")
    with pytest.raises(ValueError, match="feature-spec"):
        registry.assert_live_spec(model)


def test_price_plus_news_passes_live() -> None:
    from app.ml.features import FeatureLabelSpec

    spec = FeatureLabelSpec(
        feature_columns=FEATURE_COLUMNS,
        news_version=news_mod.NEWS_FEATURE_SPEC_VERSION,
    )
    registry.assert_live_spec(_model(spec))


def test_price_plus_news_refused_on_stale_news_version() -> None:
    from app.ml.features import FeatureLabelSpec

    # Price version current, news version stale → must be refused.
    spec = FeatureLabelSpec(news_version="v0-stale-news")
    with pytest.raises(ValueError, match="news feature-spec"):
        registry.assert_live_spec(_model(spec))


def test_news_drift_caught_even_when_price_matches(monkeypatch) -> None:
    from app.ml.features import FeatureLabelSpec

    spec = FeatureLabelSpec(news_version=news_mod.NEWS_FEATURE_SPEC_VERSION)
    model = _model(spec)
    # A news computation change that bumps the live news version must refuse the
    # model even though its price version still matches.
    monkeypatch.setattr(news_mod, "NEWS_FEATURE_SPEC_VERSION", "v2-news")
    with pytest.raises(ValueError, match="news feature-spec"):
        registry.assert_live_spec(model)


def test_model_metadata_news_fields_default_none() -> None:
    from app.ml.registry import ModelMetadata

    # Old-style construction (no news kwargs) still works and defaults to None.
    meta = ModelMetadata(
        model_id="x",
        feature_spec_version="v1",
        feature_columns=list(FEATURE_COLUMNS),
        horizon=5,
        deadband=0.0,
        symbols=["SPY"],
        train_start="2020-01-01",
        train_end="2021-01-01",
        lgbm_params={},
        seed=0,
        num_threads=1,
        calibration="none",
        calibrated=False,
        enter_threshold=0.5,
        exit_threshold=0.45,
        min_hold=5,
        n_fit=1,
        n_calib=1,
        n_thresh=1,
        effective_n=1.0,
        selection_config={},
        validation_metrics={},
        code_git_hash="abc",
        code_dirty=False,
        code_diff_hash=None,
        artifact_hash="h",
    )
    assert meta.news_feature_spec_version is None
    assert meta.annotation_model_id is None
    assert meta.annotation_prompt_version is None
    assert meta.news_feature_config is None
