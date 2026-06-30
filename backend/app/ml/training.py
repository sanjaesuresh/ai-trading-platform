"""LightGBM training pipeline with leakage-safe, purpose-partitioned in-sample folds.

Given a pooled panel (``app.ml.features``) and the positional indices of one outer
training window, ``train_model`` fits a gradient-boosted-tree classifier and returns a
``TrainedModel`` ready for the engine. The in-sample window is split — time-ordered,
purged, and embargoed — into three distinct sub-slices by purpose (plan 3.2):

- **fit**: trains the booster (sample-weighted by label uniqueness),
- **calibrate**: the early-stopping watch set *and* the probability calibrator,
- **threshold**: where the enter/exit thresholds are chosen, never the rows the
  calibrator was just fit on.

Determinism needs more than a seed: LightGBM's multithreaded histogram build is not
bit-reproducible, so the trainer pins single-thread deterministic flags (and the thread
count is recorded in the registry) so the determinism test is stable, not flaky.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import brier_score_loss, roc_auc_score

from app.evaluation.walk_forward import purged_time_folds
from app.ml.features import (
    COL_FWD_RETURN,
    COL_LABEL,
    COL_WEIGHT,
    FeatureLabelSpec,
    effective_sample_size,
)
from app.ml.model import TrainedModel

log = logging.getLogger(__name__)

# Conservative defaults: shallow trees, strong regularization, modest learning rate.
# Tabular daily-bar data is tiny and noisy; a deep model would memorize it.
DEFAULT_LGBM_PARAMS: dict[str, Any] = {
    "n_estimators": 400,
    "learning_rate": 0.03,
    "num_leaves": 15,
    "max_depth": 4,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
}


class TrainingError(ValueError):
    """Training cannot proceed (e.g. an in-sample fold has a single class)."""


@dataclass(frozen=True)
class TrainingConfig:
    spec: FeatureLabelSpec = field(default_factory=FeatureLabelSpec)
    lgbm_params: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_LGBM_PARAMS)
    )
    seed: int = 42
    num_threads: int = 1
    fit_fraction: float = 0.6
    calib_fraction: float = 0.2
    # threshold fold takes the remainder (1 - fit - calib).
    calibration: str = "isotonic"  # "isotonic" | "sigmoid" | "none"
    early_stopping_rounds: int = 50
    # All-in cost per fill in bps (fees + slippage); a round trip charges twice.
    cost_bps: float = 10.0
    hysteresis_gap: float = 0.05
    enter_grid_lo: float = 0.50
    enter_grid_hi: float = 0.70
    enter_grid_step: float = 0.02
    min_selected: int = 20
    min_hold: int | None = None  # default = spec.horizon
    # Optional pluggable estimator. When None (the default) the trainer fits the
    # standard LightGBM booster with early stopping + uniqueness weighting. When
    # set, the factory returns a fitted-on-call sklearn estimator (e.g. the
    # logistic-regression floor in M3b) that travels through the IDENTICAL purged
    # fit/calibrate/threshold folds, so a baseline shares one selection pipeline
    # with the model rather than reimplementing it. Additive and backward
    # compatible: leaving it None reproduces the prior behaviour exactly.
    estimator_factory: Callable[[TrainingConfig], Any] | None = None


@dataclass
class TrainingResult:
    model: TrainedModel
    validation_metrics: dict[str, float]
    n_fit: int
    n_calib: int
    n_thresh: int
    effective_n: float
    train_start: pd.Timestamp
    train_end: pd.Timestamp


def _annualization(horizon: int) -> float:
    return float(np.sqrt(252.0 / horizon))


def _enter_grid(config: TrainingConfig) -> np.ndarray:
    return np.arange(
        config.enter_grid_lo,
        config.enter_grid_hi + 1e-9,
        config.enter_grid_step,
    )


def _select_thresholds(
    proba: np.ndarray,
    fwd_return: np.ndarray,
    weights: np.ndarray,
    config: TrainingConfig,
) -> tuple[float, float, int, float]:
    """Choose enter/exit thresholds by a cost-aware, uniqueness-weighted score.

    For each candidate enter threshold, "long" rows are those with P(up) >= threshold;
    the score is a uniqueness-weighted, annualized mean/std of their forward returns net
    of a round-trip cost. Weighting deflates clustered overlapping rows so the score is
    not inflated by the most-correlated periods. The exit threshold sits a fixed
    hysteresis gap below enter (the engine enforces the actual whipsaw control).

    This is an in-sample *selection* score over per-row overlapping returns, NOT the
    strategy's Sharpe — the real cost-aware verdict is M3's out-of-sample backtest.
    Returns ``(enter, exit, n_selected, best_score)``; falls back to ``enter = grid_lo``
    if no candidate clears ``min_selected``.
    """
    round_trip_cost = 2.0 * config.cost_bps / 10_000.0
    ann = _annualization(config.spec.horizon)
    best_enter = config.enter_grid_lo
    best_score = -np.inf
    best_n = 0
    for enter in _enter_grid(config):
        sel = proba >= enter
        n_sel = int(sel.sum())
        if n_sel < config.min_selected:
            continue
        net = fwd_return[sel] - round_trip_cost
        w = weights[sel]
        w_sum = float(w.sum())
        if w_sum <= 0:
            continue
        mean = float(np.sum(w * net) / w_sum)
        var = float(np.sum(w * (net - mean) ** 2) / w_sum)
        score = mean * ann / np.sqrt(var) if var > 0 else mean
        if score > best_score:
            best_score, best_enter, best_n = score, float(enter), n_sel
    exit_threshold = max(0.0, best_enter - config.hysteresis_gap)
    return best_enter, exit_threshold, best_n, best_score


def _build_classifier(
    config: TrainingConfig, *, n_estimators_cap: int | None = None
) -> lgb.LGBMClassifier:
    params = dict(config.lgbm_params)
    if n_estimators_cap is not None:
        params["n_estimators"] = min(int(params.get("n_estimators", 400)), n_estimators_cap)
    # n_jobs maps to LightGBM's num_threads; single-thread + deterministic + row-wise
    # histogram build is what makes training bit-reproducible (the §13 determinism test).
    return lgb.LGBMClassifier(
        **params,
        random_state=config.seed,
        n_jobs=config.num_threads,
        deterministic=True,
        force_row_wise=True,
        verbose=-1,
    )


# When the calibration fold can't serve as an early-stopping watch set (single class),
# cap the tree count so the booster can't run the full schedule unwatched on thin data.
_NO_EARLY_STOP_TREE_CAP = 100


def train_model(
    panel: pd.DataFrame,
    train_idx: np.ndarray,
    *,
    config: TrainingConfig | None = None,
) -> TrainingResult:
    """Fit a calibrated LightGBM classifier on one outer training window.

    Raises ``TrainingError`` if the window is unusable (empty, or the fit fold has a
    single class). Probability calibration is skipped (with a logged note) when the
    calibration fold is too small or single-class, in which case the raw booster
    probabilities are used; the result records whether calibration was applied.
    """
    config = config or TrainingConfig()
    spec = config.spec
    cols = list(spec.feature_columns)
    min_hold = config.min_hold if config.min_hold is not None else spec.horizon

    train_idx = np.asarray(train_idx)
    if train_idx.size == 0:
        raise TrainingError("Empty training window.")

    fractions = [
        config.fit_fraction,
        config.calib_fraction,
        max(0.0, 1.0 - config.fit_fraction - config.calib_fraction),
    ]
    fit_idx, calib_idx, thresh_idx = purged_time_folds(
        panel, train_idx, fractions, horizon=spec.horizon
    )
    if fit_idx.size == 0:
        raise TrainingError("Fit fold is empty after purge/embargo.")

    y_fit = panel.loc[fit_idx, COL_LABEL].astype(int).to_numpy()
    if len(np.unique(y_fit)) < 2:
        raise TrainingError("Fit fold has a single class; cannot train a classifier.")

    # Carry feature names through fit and predict (consistent DataFrames) so the
    # classifier's feature-name safety check stays meaningful instead of warning.
    x_fit = panel.loc[fit_idx, cols]
    w_fit = panel.loc[fit_idx, COL_WEIGHT].to_numpy(dtype=float)

    calib_has_both = calib_idx.size > 0 and (
        len(np.unique(panel.loc[calib_idx, COL_LABEL].astype(int))) == 2
    )
    x_calib = panel.loc[calib_idx, cols]
    y_calib = panel.loc[calib_idx, COL_LABEL].astype(int).to_numpy()

    base: Any
    if config.estimator_factory is not None:
        # Pluggable non-LightGBM estimator (the M3b logistic floor). Early stopping
        # and uniqueness sample-weighting are LightGBM-specific, so the generic path
        # fits the bare estimator on the fit fold only. The estimator (e.g. a
        # StandardScaler+LogisticRegression pipeline) therefore still sees ONLY the
        # training rows — the no-leakage property that matters — and the SAME
        # threshold-selection fold below chooses its enter/exit thresholds.
        base = config.estimator_factory(config)
        base.fit(x_fit, y_fit)
    else:
        # Without a usable early-stopping watch set, cap the tree count so the booster
        # can't run its full schedule unwatched on thin data.
        base = _build_classifier(
            config, n_estimators_cap=None if calib_has_both else _NO_EARLY_STOP_TREE_CAP
        )
        fit_kwargs: dict[str, Any] = {"sample_weight": w_fit}
        if calib_has_both:
            fit_kwargs["eval_set"] = [(x_calib, y_calib)]
            fit_kwargs["eval_metric"] = "auc"
            fit_kwargs["callbacks"] = [
                lgb.early_stopping(config.early_stopping_rounds, verbose=False),
                lgb.log_evaluation(0),
            ]
        base.fit(x_fit, y_fit, **fit_kwargs)

    classifier: object = base
    calibrated = False
    if config.calibration != "none" and calib_has_both and calib_idx.size >= 10:
        try:
            cal = CalibratedClassifierCV(
                FrozenEstimator(base), method=config.calibration
            )
            cal.fit(x_calib, y_calib)
            classifier = cal
            calibrated = True
        except ValueError as exc:  # too few samples per fold for the internal CV
            log.info("Calibration skipped (%s); using raw booster probabilities.", exc)

    # Threshold selection on the distinct threshold fold (held out from both the
    # booster fit and the calibrator), uniqueness-weighted.
    if thresh_idx.size > 0:
        proba_t = _proba_up(classifier, panel.loc[thresh_idx, cols])
        fwd_t = panel.loc[thresh_idx, COL_FWD_RETURN].to_numpy(dtype=float)
        w_t = panel.loc[thresh_idx, COL_WEIGHT].to_numpy(dtype=float)
        enter, exit_, n_sel, score = _select_thresholds(proba_t, fwd_t, w_t, config)
    else:
        enter, exit_, n_sel, score = config.enter_grid_lo, max(
            0.0, config.enter_grid_lo - config.hysteresis_gap
        ), 0, float("nan")

    model = TrainedModel(
        classifier=classifier,
        spec=spec,
        enter_threshold=enter,
        exit_threshold=exit_,
        min_hold=min_hold,
        calibrated=calibrated,
    )

    # Diagnostics on the held-out threshold fold, NOT the calibrator's own fold —
    # so a flattering in-sample-on-calibration Brier can't masquerade as a clean score.
    metrics = _validation_metrics(classifier, panel, thresh_idx, cols)
    metrics.update(
        {
            "enter_threshold": float(enter),
            "exit_threshold": float(exit_),
            "n_selected_thresh": float(n_sel),
            "threshold_grid_size": float(len(_enter_grid(config))),
            # In-sample per-row selection score over overlapping returns — NOT a Sharpe.
            "threshold_selection_score": float(score),
        }
    )

    decision_ts = panel.loc[train_idx, "decision_ts"]
    return TrainingResult(
        model=model,
        validation_metrics=metrics,
        n_fit=int(fit_idx.size),
        n_calib=int(calib_idx.size),
        n_thresh=int(thresh_idx.size),
        effective_n=effective_sample_size(panel.loc[train_idx, COL_WEIGHT]),
        train_start=pd.Timestamp(decision_ts.min()),
        train_end=pd.Timestamp(decision_ts.max()),
    )


def _proba_up(classifier: object, features: pd.DataFrame) -> np.ndarray:
    proba = classifier.predict_proba(features)  # type: ignore[attr-defined]
    classes = list(classifier.classes_)  # type: ignore[attr-defined]
    return np.asarray(proba)[:, classes.index(1)]


def _validation_metrics(
    classifier: object, panel: pd.DataFrame, calib_idx: np.ndarray, cols: list[str]
) -> dict[str, float]:
    """Classification diagnostics on the calibration fold (context, not the verdict)."""
    if calib_idx.size == 0:
        return {"auc": float("nan"), "brier": float("nan")}
    y = panel.loc[calib_idx, COL_LABEL].astype(int).to_numpy()
    if len(np.unique(y)) < 2:
        return {"auc": float("nan"), "brier": float("nan")}
    proba = _proba_up(classifier, panel.loc[calib_idx, cols])
    return {
        "auc": float(roc_auc_score(y, proba)),
        "brier": float(brier_score_loss(y, proba)),
    }
