"""ML pipeline orchestration (Phase 4 M4).

Mirrors evaluation_service: load → quality-gate → features → train/evaluate →
persist. Two flows:

- **train_and_register**: Build inputs, train one model on the most-recent
  in-sample window (all stored bars up to ``req.train_end``, or all available bars
  when omitted), save the artifact + JSON sidecar via ``save_model``, write the
  ``MLModel`` row from the returned ``ModelMetadata``. Synchronous — training a
  single window is fast enough to run in the request.

- **run_ml_walk_forward** / **run_ml_backtest**: Load inputs, drive the
  ``evaluate_ml_walk_forward`` runner (or, for a pinned backtest, load the model
  artifact + run through the engine), store ``result.to_dict()`` into ``run.results``
  on the ``EvaluationRun`` row, mark completed.

- **create_queued_ml_run** / **execute_ml_run**: ARQ-facing lifecycle — creates a
  queued ``EvaluationRun`` row with an ML kind and ``config`` JSON, then (on the
  worker side) dispatches to walk-forward vs backtest by kind with the standard
  ``mark_running`` / ``mark_failed`` flow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.data.data_quality import check_data_quality
from app.data.db_loader import orm_rows_to_frame, query_market_data
from app.data.feature_engineering import add_technical_indicators
from app.ml.evaluation import evaluate_ml_walk_forward
from app.ml.features import (
    FeatureLabelSpec,
    build_pooled_panel,
)
from app.ml.registry import ModelMetadata, load_model, save_model
from app.ml.training import TrainingConfig, train_model
from app.models_db.evaluation_run import EvaluationRun
from app.models_db.ml_model import MLModel
from app.schemas.ml import (
    MLBacktestRequest,
    MLPortfolioWalkForwardRequest,
    MLTrainRequest,
    MLWalkForwardRequest,
)
from app.services.backtest_service import BacktestRequestError
from app.services.evaluation_service import sanitize_result_dict

log = get_logger(__name__)

# -------------------------------------------------------------------------
# Shared data-loading helper
# -------------------------------------------------------------------------


def _load_featured_frame(db: Session, symbol: str) -> Any:
    """Query DB → ORM rows → OHLCV frame → quality gate → indicators.

    Mirrors ``load_and_feature_frame`` but DB-only (ML pipeline always reads from
    the DB; no CSV path in the ML routes). Raises ``BacktestRequestError`` on any
    client-correctable problem.
    """
    rows = query_market_data(db, symbol)
    if not rows:
        raise BacktestRequestError(
            f"No market data found in the database for symbol '{symbol}'. "
            "Run ingestion for this symbol first."
        )
    frame = orm_rows_to_frame(rows)
    report = check_data_quality(frame)
    if not report.passed:
        raise BacktestRequestError(
            f"Data quality check failed for '{symbol}'.", report.errors
        )
    return add_technical_indicators(frame)


def build_ml_inputs(
    db: Session,
    symbols: list[str],
    spec: FeatureLabelSpec | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Build the pooled panel and per-symbol featured frames for the given symbols.

    For each symbol: ``query_market_data`` → ``orm_rows_to_frame`` → data-quality
    gate (aborts on blocking errors) → ``add_technical_indicators`` →
    ``build_symbol_panel`` (feature columns + labels + uniqueness weights) into
    ``frames[symbol]``. Then ``build_pooled_panel(frames, spec)`` → ``panel``.

    Returns ``(panel, frames)`` where ``frames`` maps each symbol to its full
    featured+indicator DataFrame (OHLCV + indicators + f_* features), not just the
    panel slice — the evaluation engine needs the full frame to slice OOS windows.
    """
    spec = spec or FeatureLabelSpec()
    featured_frames: dict[str, Any] = {}
    for symbol in symbols:
        featured_frames[symbol] = _load_featured_frame(db, symbol)

    # ``build_pooled_panel`` expects the full featured frames; it internally calls
    # ``build_symbol_panel`` on each. We return both the full frames (for the engine)
    # and the pooled panel (for the trainer / splitter).
    panel, reports = build_pooled_panel(featured_frames, spec=spec)
    for r in reports:
        log.debug(
            "ML inputs %s: %d rows in → %d final panel rows (-%d warmup, -%d tail, -%d neutral).",
            r.symbol, r.rows_input, r.rows_final,
            r.dropped_warmup, r.dropped_tail_unlabelable, r.dropped_neutral,
        )
    return panel, featured_frames


# -------------------------------------------------------------------------
# Training
# -------------------------------------------------------------------------


def train_and_register(db: Session, req: MLTrainRequest) -> MLModel:
    """Build inputs, train a model on the most-recent in-sample window, register it.

    Training window choice: all stored bars up to ``req.train_end`` (if provided)
    or all available bars (when ``train_end`` is None). This is a single, greedy
    in-sample fit — not a walk-forward split — so the model is trained on as much
    data as possible. The evaluation routes run walk-forward splits separately so
    the honest OOS verdict is available before deploying the model.

    Steps: build pooled panel → use all panel row indices as the training window
    → ``train_model`` → ``save_model`` (writes artifact + JSON sidecar to
    ``get_settings().model_path``) → insert ``MLModel`` row → return the row.
    """
    import numpy as np

    spec = FeatureLabelSpec(horizon=req.horizon, deadband=req.deadband)
    config = _build_training_config(req, spec)

    panel, _frames = build_ml_inputs(db, req.symbols, spec)
    if panel.empty:
        raise BacktestRequestError(
            "No usable rows in the pooled panel after quality gate and label drop. "
            "Provide more history or reduce the deadband."
        )

    # Filter to train_end if requested (use all rows otherwise).
    # Use pd.Timestamp comparison rather than string coercion: lexicographic
    # string comparison silently drops intraday timestamps on the cutoff day
    # (e.g. "2023-12-29 16:00" > "2023-12-29" as strings but should be <=).
    # The cutoff is train_end-inclusive, so extend to the start of the next day.
    if req.train_end is not None:
        import pandas as _pd

        cutoff = req.train_end
        cutoff_ts = _pd.Timestamp(cutoff) + _pd.Timedelta(days=1)
        mask = panel["decision_ts"] < cutoff_ts
        panel = panel.loc[mask].reset_index(drop=True)
        if panel.empty:
            raise BacktestRequestError(
                f"No panel rows at or before train_end='{cutoff}'."
            )

    train_idx = np.arange(len(panel))
    result = train_model(panel, train_idx, config=config)

    model_dir = get_settings().model_path
    metadata = save_model(
        result,
        symbols=req.symbols,
        config=config,
        model_dir=model_dir,
    )

    row = _upsert_ml_model_row(db, metadata)
    log.info(
        "ML model %s registered (symbols=%s, horizon=%d, calibrated=%s).",
        row.model_id, req.symbols, req.horizon, row.calibrated,
    )
    return row


def _build_training_config(req: MLTrainRequest, spec: FeatureLabelSpec) -> TrainingConfig:
    """Assemble a ``TrainingConfig`` from an ``MLTrainRequest``."""
    from app.ml.training import DEFAULT_LGBM_PARAMS

    lgbm = dict(DEFAULT_LGBM_PARAMS)
    lgbm.update(req.lgbm_params)
    return TrainingConfig(
        spec=spec,
        lgbm_params=lgbm,
        seed=req.seed,
        num_threads=req.num_threads,
        calibration=req.calibration,
        fit_fraction=req.fit_fraction,
        calib_fraction=req.calib_fraction,
        cost_bps=req.cost_bps,
        hysteresis_gap=req.hysteresis_gap,
        enter_grid_lo=req.enter_grid_lo,
        enter_grid_hi=req.enter_grid_hi,
        enter_grid_step=req.enter_grid_step,
        min_selected=req.min_selected,
        min_hold=req.min_hold,
    )


def _upsert_ml_model_row(db: Session, metadata: ModelMetadata) -> MLModel:
    """Insert or return the existing ``MLModel`` row for this content-hash model_id.

    ``model_id`` is a content hash: the same config + data + seed always produce
    the same hash. ``save_model`` is already idempotent on the filesystem; this
    makes the DB registration idempotent too, so re-training an identical model
    does not raise ``IntegrityError`` against the UNIQUE ``model_id`` constraint.
    """
    existing = get_ml_model(db, metadata.model_id)
    if existing is not None:
        log.info(
            "ML model %s already registered; returning existing row.", metadata.model_id
        )
        return existing
    row = _metadata_to_orm(metadata)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _metadata_to_orm(meta: ModelMetadata) -> MLModel:
    """Map a ``ModelMetadata`` dataclass to an ``MLModel`` ORM instance (DB-free)."""
    return MLModel(
        model_id=meta.model_id,
        feature_spec_version=meta.feature_spec_version,
        symbols=list(meta.symbols),
        train_start=str(meta.train_start),
        train_end=str(meta.train_end),
        horizon=int(meta.horizon),
        deadband=float(meta.deadband),
        lgbm_params=dict(meta.lgbm_params),
        seed=int(meta.seed),
        num_threads=int(meta.num_threads),
        calibration=str(meta.calibration),
        calibrated=bool(meta.calibrated),
        enter_threshold=float(meta.enter_threshold),
        exit_threshold=float(meta.exit_threshold),
        min_hold=int(meta.min_hold),
        n_fit=int(meta.n_fit),
        n_calib=int(meta.n_calib),
        n_thresh=int(meta.n_thresh),
        effective_n=float(meta.effective_n),
        selection_config=dict(meta.selection_config),
        validation_metrics=dict(meta.validation_metrics),
        code_git_hash=str(meta.code_git_hash),
        code_dirty=bool(meta.code_dirty),
        code_diff_hash=meta.code_diff_hash,
        artifact_hash=str(meta.artifact_hash),
    )


# -------------------------------------------------------------------------
# Evaluation runners
# -------------------------------------------------------------------------


def run_ml_walk_forward(db: Session, run: EvaluationRun) -> EvaluationRun:
    """Execute a walk-forward ML evaluation in place on the given run row.

    Rebuilds inputs from the stored ``config``, drives
    ``evaluate_ml_walk_forward``, stores ``result.to_dict()`` into ``run.results``,
    and marks the row ``completed``. The caller owns ``mark_running`` /
    ``mark_failed`` flips.
    """
    cfg = run.config
    req = MLWalkForwardRequest(**cfg)
    spec = FeatureLabelSpec(horizon=req.horizon, deadband=req.deadband)
    panel, frames = build_ml_inputs(db, req.symbols, spec)

    from app.ml.training import TrainingConfig

    training_config = TrainingConfig(
        spec=spec,
        seed=req.seed,
    )
    result = evaluate_ml_walk_forward(
        panel,
        frames,
        eval_symbol=req.eval_symbol,
        training_config=training_config,
        horizon=req.horizon,
        in_sample_dates=req.in_sample_dates,
        out_sample_dates=req.out_sample_dates,
        step_dates=req.step_dates,
        scheme=req.scheme,
        fee_bps=req.fee_bps,
        slippage_bps=req.slippage_bps,
        initial_capital=req.initial_capital,
        mc_runs=req.mc_runs,
        seed=req.seed,
        n_config_trials=req.n_config_trials,
    )
    run.results = sanitize_result_dict(result.to_dict())
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    log.info(
        "ML walk-forward run %s completed (eval_symbol=%s, verdict=%s).",
        run.id, req.eval_symbol, result.verdict,
    )
    return run


def run_ml_portfolio_walk_forward(db: Session, run: EvaluationRun) -> EvaluationRun:
    """Execute a multi-symbol portfolio ML walk-forward in place on the run row.

    Rebuilds the pooled panel + per-symbol featured frames from the stored
    ``config``, builds a ``PortfolioConfig`` from the request, drives
    ``evaluate_ml_portfolio_walk_forward`` (one pooled model per split through the
    shared portfolio core, per-symbol breakdown vs baselines), stores
    ``result.to_dict()`` into ``run.results``, and marks the row ``completed``.
    """
    from app.backtesting.portfolio_core import PortfolioConfig
    from app.ml.portfolio_evaluation import evaluate_ml_portfolio_walk_forward
    from app.ml.training import TrainingConfig

    cfg = run.config
    req = MLPortfolioWalkForwardRequest(**cfg)
    spec = FeatureLabelSpec(horizon=req.horizon, deadband=req.deadband)
    panel, frames = build_ml_inputs(db, req.symbols, spec)

    training_config = TrainingConfig(spec=spec, seed=req.seed)
    portfolio_config = PortfolioConfig(
        initial_capital=req.initial_capital,
        fee_bps=req.fee_bps,
        slippage_bps=req.slippage_bps,
        target_vol=req.target_vol,
        vol_lookback=req.vol_lookback,
        max_position_pct=req.max_position_pct,
        gross_exposure_cap=req.gross_exposure_cap,
        max_open_positions=req.max_open_positions,
        per_order_notional_cap=req.per_order_notional_cap,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        max_drawdown_cutoff_pct=req.max_drawdown_cutoff_pct,
    )
    result = evaluate_ml_portfolio_walk_forward(
        panel,
        frames,
        symbols=req.symbols,
        config=portfolio_config,
        training_config=training_config,
        horizon=req.horizon,
        in_sample_dates=req.in_sample_dates,
        out_sample_dates=req.out_sample_dates,
        step_dates=req.step_dates,
        scheme=req.scheme,
        n_config_trials=req.n_config_trials,
    )
    run.results = sanitize_result_dict(result.to_dict())
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    log.info(
        "ML portfolio walk-forward run %s completed (symbols=%s, beats_all=%s).",
        run.id, req.symbols, result.beats_all_baselines,
    )
    return run


def run_ml_backtest(db: Session, run: EvaluationRun) -> EvaluationRun:
    """Execute a pinned-model backtest in place on the given run row.

    Loads the registered model artifact by ``model_id``, loads the symbol's
    featured frame for the configured window, runs it through the engine with
    ``MLClassifierStrategy``, and stores the result.
    """
    from datetime import date as _date

    from app.backtesting.engine import run_backtest
    from app.backtesting.metrics import compute_metrics
    from app.strategies.ml_classifier import MLClassifierStrategy

    cfg = run.config
    req = MLBacktestRequest(**cfg)

    model_dir = get_settings().model_path
    try:
        model = load_model(req.model_id, model_dir)
    except FileNotFoundError as exc:
        raise BacktestRequestError(str(exc)) from exc

    # Load with optional date window.
    start_date = _date.fromisoformat(req.start) if req.start else None
    end_date = _date.fromisoformat(req.end) if req.end else None
    rows = query_market_data(db, req.symbol, start=start_date, end=end_date)
    if not rows:
        raise BacktestRequestError(
            f"No market data found for symbol '{req.symbol}' in the requested window."
        )
    frame = orm_rows_to_frame(rows)
    quality_report = check_data_quality(frame)
    if not quality_report.passed:
        raise BacktestRequestError(
            f"Data quality check failed for '{req.symbol}'.", quality_report.errors
        )
    featured = add_technical_indicators(frame)

    strategy = MLClassifierStrategy.from_model(model)
    backtest_result = run_backtest(
        featured,
        strategy,
        symbol=req.symbol,
        initial_capital=req.initial_capital,
        fee_bps=req.fee_bps,
        slippage_bps=req.slippage_bps,
    )
    metrics = compute_metrics(
        backtest_result.equity_curve, backtest_result.trades, req.initial_capital
    )
    from dataclasses import asdict as _asdict
    run.results = sanitize_result_dict({
        "model_id": req.model_id,
        "symbol": req.symbol,
        "total_return_pct": float(backtest_result.total_return_pct),
        "metrics": _asdict(metrics),
        "num_trades": int(len(backtest_result.trades)),
    })
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    log.info(
        "ML backtest run %s completed (model=%s, symbol=%s, return=%.2f%%).",
        run.id, req.model_id, req.symbol, backtest_result.total_return_pct,
    )
    return run


# -------------------------------------------------------------------------
# Queued-run lifecycle (ARQ path)
# -------------------------------------------------------------------------


def create_queued_ml_run(
    req: MLWalkForwardRequest | MLBacktestRequest | MLPortfolioWalkForwardRequest,
    *,
    kind: str,
    db: Session,
) -> EvaluationRun:
    """Persist a ``queued`` EvaluationRun row for an ML evaluation.

    ``kind`` must be ``"ml_walk_forward"``, ``"ml_backtest"``, or
    ``"ml_portfolio_wf"`` (the multi-symbol portfolio walk-forward — abbreviated to
    fit the 16-char ``kind`` column). The typed request is stored as ``config``
    JSON; ``symbol`` carries the eval symbol (walk-forward), the backtest symbol, or
    the basket label (portfolio). ``strategy_name`` is always ``"ml_classifier"``.
    """
    if kind not in ("ml_walk_forward", "ml_backtest", "ml_portfolio_wf"):
        raise ValueError(f"Unknown ML evaluation kind: {kind!r}.")

    if isinstance(req, MLWalkForwardRequest):
        symbol = req.eval_symbol
    elif isinstance(req, MLPortfolioWalkForwardRequest):
        # Basket label; the full list lives in config.symbols. Truncate to the
        # 32-char column so a large basket never overflows.
        symbol = ",".join(req.symbols)[:32]
    else:
        symbol = req.symbol

    run = EvaluationRun(
        kind=kind,
        symbol=symbol,
        strategy_name="ml_classifier",
        status="queued",
        objective="sharpe_ratio",  # ML evaluations use their own significance verdict
        config=req.model_dump(),
        results={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_running(db: Session, run: EvaluationRun) -> EvaluationRun:
    """Flip a queued run to ``running`` and commit (mirrors evaluation_service)."""
    run.status = "running"
    db.commit()
    db.refresh(run)
    return run


def mark_failed(db: Session, run: EvaluationRun, error: str) -> EvaluationRun:
    """Flip a run to ``failed``, record the error and finish time, and commit."""
    run.status = "failed"
    run.error = error
    run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run


def execute_ml_run(db: Session, run: EvaluationRun) -> EvaluationRun:
    """Dispatch to walk-forward or backtest runner by ``run.kind``.

    The caller owns ``mark_running`` before this and ``mark_failed`` on error.
    """
    if run.kind == "ml_walk_forward":
        return run_ml_walk_forward(db, run)
    if run.kind == "ml_portfolio_wf":
        return run_ml_portfolio_walk_forward(db, run)
    if run.kind == "ml_backtest":
        return run_ml_backtest(db, run)
    raise ValueError(f"Unknown ML evaluation kind: {run.kind!r}.")


# -------------------------------------------------------------------------
# Model registry queries
# -------------------------------------------------------------------------


def list_ml_models(db: Session) -> list[MLModel]:
    """Return all registered models, newest-first by train_end."""
    return list(
        db.scalars(
            select(MLModel).order_by(MLModel.train_end.desc(), MLModel.id.desc())
        ).all()
    )


def get_ml_model(db: Session, model_id: str) -> MLModel | None:
    """Return one registered model by ``model_id``, or ``None`` if not found."""
    return db.scalars(
        select(MLModel).where(MLModel.model_id == model_id)
    ).first()
