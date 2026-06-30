"""Request/response contracts for the ML pipeline (Phase 4 M4).

``MLTrainRequest`` drives training + registry insertion. ``MLWalkForwardRequest`` /
``MLBacktestRequest`` enqueue background evaluation runs. The detail/summary shapes
mirror the evaluation schemas so the frontend can render them consistently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator  # noqa: TC002

# ---------------------------------------------------------------------------
# Training request
# ---------------------------------------------------------------------------


class MLTrainRequest(BaseModel):
    """Inputs for training one model and registering it.

    ``symbols`` is the training pool. Training uses all available DB rows for
    those symbols up to (and including) ``train_end`` when provided, or all
    stored bars when omitted — effectively a full in-sample window on available
    history. Document the choice: this makes the registered model comparable to
    evaluation splits whose in-sample window ends at the same date.
    """

    symbols: list[str] = Field(min_length=1, description="Training-pool symbols (>=1).")
    train_end: str | None = Field(
        default=None,
        description=(
            "ISO date (YYYY-MM-DD) upper bound for the training window. "
            "Omit to use all available stored bars."
        ),
    )

    # FeatureLabelSpec knobs
    horizon: int = Field(default=5, ge=1, description="Forecast horizon in bars.")
    deadband: float = Field(
        default=0.0, ge=0.0, description="Neutral label deadband (fractional return)."
    )

    # TrainingConfig knobs (the most commonly tuned)
    seed: int = Field(default=42)
    num_threads: int = Field(default=1, ge=1)
    calibration: str = Field(
        default="isotonic",
        description="Probability calibration method: 'isotonic', 'sigmoid', or 'none'.",
    )
    fit_fraction: float = Field(default=0.6, gt=0, lt=1.0)
    calib_fraction: float = Field(default=0.2, gt=0, lt=1.0)
    cost_bps: float = Field(default=10.0, ge=0)
    hysteresis_gap: float = Field(default=0.05, ge=0)
    enter_grid_lo: float = Field(default=0.50, ge=0, le=1.0)
    enter_grid_hi: float = Field(default=0.70, ge=0, le=1.0)
    enter_grid_step: float = Field(default=0.02, gt=0)
    min_selected: int = Field(default=20, ge=1)
    min_hold: int | None = Field(
        default=None, ge=1, description="Minimum holding bars; defaults to horizon."
    )
    lgbm_params: dict[str, Any] = Field(
        default_factory=dict,
        description="LightGBM hyperparameter overrides (merged over defaults).",
    )

    @model_validator(mode="after")
    def _symbols_not_empty(self) -> MLTrainRequest:
        cleaned = [s.strip() for s in self.symbols if s.strip()]
        if not cleaned:
            raise ValueError("symbols must contain at least one non-empty string.")
        self.symbols = cleaned
        return self


# ---------------------------------------------------------------------------
# Model list/detail
# ---------------------------------------------------------------------------


class MLModelSummary(BaseModel):
    """One row in the model registry list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    model_id: str
    feature_spec_version: str
    symbols: list[str]
    train_start: str
    train_end: str
    horizon: int
    deadband: float
    calibrated: bool
    enter_threshold: float
    exit_threshold: float
    created_at: datetime


class MLModelDetail(MLModelSummary):
    """Full model detail including all config and validation metrics."""

    lgbm_params: dict
    seed: int
    num_threads: int
    calibration: str
    min_hold: int
    n_fit: int
    n_calib: int
    n_thresh: int
    effective_n: float
    selection_config: dict
    validation_metrics: dict
    code_git_hash: str
    code_dirty: bool
    code_diff_hash: str | None
    artifact_hash: str


# ---------------------------------------------------------------------------
# Walk-forward evaluation request
# ---------------------------------------------------------------------------


class MLWalkForwardRequest(BaseModel):
    """Inputs for a walk-forward ML evaluation.

    ``symbols`` is the training pool; ``eval_symbol`` (which must appear in
    ``symbols``) is the single symbol the engine scores OOS.
    """

    symbols: list[str] = Field(min_length=1)
    eval_symbol: str = Field(min_length=1, max_length=32)

    # Walk-forward policy
    scheme: str = Field(
        default="anchored",
        description="'anchored' (expanding window) or 'rolling' (fixed window).",
    )
    in_sample_dates: int = Field(default=504, ge=2)
    out_sample_dates: int = Field(default=126, ge=2)
    step_dates: int = Field(default=126, ge=1)

    # Feature/label knobs
    horizon: int = Field(default=5, ge=1)
    deadband: float = Field(default=0.0, ge=0.0)

    # Engine costs
    fee_bps: float = Field(default=5.0, ge=0, le=1000)
    slippage_bps: float = Field(default=5.0, ge=0, le=1000)
    initial_capital: float = Field(default=100_000.0, gt=0)

    # Significance
    mc_runs: int = Field(default=200, ge=1)
    seed: int = Field(default=42)
    n_config_trials: int | None = Field(
        default=None, ge=1,
        description="DSR trial count override; defaults to the documented floor.",
    )

    @model_validator(mode="after")
    def _eval_in_symbols(self) -> MLWalkForwardRequest:
        cleaned = [s.strip() for s in self.symbols if s.strip()]
        if not cleaned:
            raise ValueError("symbols must contain at least one non-empty string.")
        self.symbols = cleaned
        if self.eval_symbol not in self.symbols:
            raise ValueError(
                f"eval_symbol '{self.eval_symbol}' must be in symbols {self.symbols}."
            )
        return self


# ---------------------------------------------------------------------------
# Multi-symbol portfolio walk-forward evaluation request (M6)
# ---------------------------------------------------------------------------


class MLPortfolioWalkForwardRequest(BaseModel):
    """Inputs for a multi-symbol ML walk-forward through the Phase 3 portfolio core.

    ``symbols`` is BOTH the pooled training basket and the OOS basket: one pooled
    model per split is driven multi-symbol through the shared portfolio core and
    judged per symbol and against the rule / buy-and-hold-basket / single-position
    baselines, net of fees. Unlike the single-symbol walk-forward there is no
    ``eval_symbol`` — every symbol is scored as part of the portfolio.
    """

    symbols: list[str] = Field(min_length=1, description="Pooled + OOS basket (>=1).")

    # Walk-forward policy
    scheme: str = Field(
        default="anchored",
        description="'anchored' (expanding window) or 'rolling' (fixed window).",
    )
    in_sample_dates: int = Field(default=504, ge=2)
    out_sample_dates: int = Field(default=126, ge=2)
    step_dates: int = Field(default=126, ge=1)

    # Feature/label knobs
    horizon: int = Field(default=5, ge=1)
    deadband: float = Field(default=0.0, ge=0.0)

    # Portfolio execution config (PortfolioConfig knobs)
    fee_bps: float = Field(default=5.0, ge=0, le=1000)
    slippage_bps: float = Field(default=5.0, ge=0, le=1000)
    initial_capital: float = Field(default=100_000.0, gt=0)
    target_vol: float | None = Field(default=None, gt=0)
    vol_lookback: int = Field(default=20, ge=1)
    max_position_pct: float = Field(default=0.95, gt=0, le=1.0)
    gross_exposure_cap: float = Field(default=1.0, gt=0)
    max_open_positions: int = Field(default=5, ge=1)
    per_order_notional_cap: float | None = Field(default=None, gt=0)
    stop_loss_pct: float | None = Field(default=None, gt=0, le=1.0)
    take_profit_pct: float | None = Field(default=None, gt=0)
    max_drawdown_cutoff_pct: float | None = Field(default=None, gt=0, le=1.0)

    # Significance
    seed: int = Field(default=42)
    n_config_trials: int | None = Field(
        default=None, ge=1,
        description="DSR trial count override; defaults to the documented floor.",
    )

    @model_validator(mode="after")
    def _symbols_not_empty(self) -> MLPortfolioWalkForwardRequest:
        cleaned = [s.strip() for s in self.symbols if s.strip()]
        if not cleaned:
            raise ValueError("symbols must contain at least one non-empty string.")
        self.symbols = cleaned
        return self


# ---------------------------------------------------------------------------
# Pinned-model backtest request
# ---------------------------------------------------------------------------


class MLBacktestRequest(BaseModel):
    """Inputs for a pinned-model OOS backtest.

    Loads a previously registered model by ``model_id``, rebuilds its eval
    symbol's featured frame for the given window, and scores it through the engine.
    """

    model_id: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=1, max_length=32)

    # Optional date window (ISO strings); None means use all available bars.
    start: str | None = Field(default=None)
    end: str | None = Field(default=None)

    fee_bps: float = Field(default=5.0, ge=0, le=1000)
    slippage_bps: float = Field(default=5.0, ge=0, le=1000)
    initial_capital: float = Field(default=100_000.0, gt=0)


# ---------------------------------------------------------------------------
# Evaluation detail (reuses the EvaluationRun shape, ML-typed results blob)
# ---------------------------------------------------------------------------


class MLEvaluationSummary(BaseModel):
    """One row in the ML evaluations list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    # For ML kinds, symbol carries the eval_symbol (walk-forward) or the symbol
    # (backtest). strategy_name is "ml_classifier".
    symbol: str
    strategy_name: str
    status: str
    objective: str
    created_at: datetime


class MLEvaluationDetail(MLEvaluationSummary):
    """Full ML evaluation detail: summary plus config and results blobs."""

    config: dict
    results: dict
