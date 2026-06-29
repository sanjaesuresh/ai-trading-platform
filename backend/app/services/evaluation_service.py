"""Orchestrates one evaluation run (sweep or walk-forward) and persists it.

Mirrors the ``backtest_service`` seam: load → quality-gate → feature (shared
``load_and_feature_frame``) → drive the evaluation runner → serialize → persist
one ``EvaluationRun`` row. The size guard rejects an oversized grid with a clean
4xx *before* any data is loaded, so a typo'd grid never silently truncates or
burns a load. The runner is deterministic, so a failed run raises before
persistence rather than leaving a partial row (M6 will add the queued/failed
lifecycle).
"""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.backtesting.metrics import Metrics
from app.core.logging import get_logger
from app.evaluation.grid import count_combinations, expand_param_grid
from app.evaluation.reporting import (
    CombinationResult,
    DistributionSummary,
    SplitResult,
    WalkForwardResult,
)
from app.evaluation.runner import run_sweep, run_walk_forward
from app.evaluation.walk_forward import generate_splits
from app.models_db.evaluation_run import EvaluationRun
from app.schemas.evaluation import SweepRequest, WalkForwardRequest
from app.services.backtest_service import BacktestRequestError, load_and_feature_frame
from app.strategies.registry import StrategyParamError, UnknownStrategyError

log = get_logger(__name__)

# Profit factor is +inf when a run has only winners; store a large finite stand-in
# so the JSON column stays valid (mirrors backtest_service._finite).
_PROFIT_FACTOR_INF = 1.0e9


def validate_and_expand(req: SweepRequest) -> list[dict[str, Any]]:
    """Size-guard then expand the grid, surfacing all errors as request errors.

    Checks ``count_combinations`` against ``max_combinations`` first (cheap, no
    expansion), then expands — which validates every combination against the
    strategy's param model. Unknown strategy / invalid params / oversized grid all
    become a clean ``BacktestRequestError`` (HTTP 400).
    """
    empty_keys = [key for key, values in req.param_grid.items() if not values]
    if empty_keys:
        raise BacktestRequestError(
            f"Parameter grid has empty value list(s) for: {', '.join(empty_keys)}. "
            "Give each swept parameter at least one value."
        )
    n = count_combinations(req.param_grid)
    if n > req.max_combinations:
        raise BacktestRequestError(
            f"Parameter grid expands to {n} combinations, over the limit of "
            f"{req.max_combinations}. Narrow the grid or raise max_combinations."
        )
    try:
        return expand_param_grid(req.strategy_name, req.param_grid)
    except (UnknownStrategyError, StrategyParamError) as exc:
        raise BacktestRequestError(str(exc)) from exc


def _run_kwargs(req: SweepRequest) -> dict[str, Any]:
    """Engine knobs passed straight through to run_backtest (net-of-fees stays the bar)."""
    return {
        "initial_capital": req.initial_capital,
        "fee_bps": req.fee_bps,
        "slippage_bps": req.slippage_bps,
        "max_position_pct": req.max_position_pct,
        "target_vol": req.target_vol,
        "vol_lookback": req.vol_lookback,
        "stop_loss_pct": req.stop_loss_pct,
        "take_profit_pct": req.take_profit_pct,
        "max_drawdown_cutoff_pct": req.max_drawdown_cutoff_pct,
    }


# Shown with every result so the multiple-testing caveat travels with the data,
# not only in the README. Testing many parameter combinations means some look
# good by luck; only the out-of-sample, cost-aware view is evidence.
_CAVEAT = (
    "Simulated only — not financial advice. Many parameter combinations were "
    "tested, so the best in-sample result is likely inflated by luck. Trust only "
    "the out-of-sample, net-of-fees distribution; a bare sweep is in-sample only."
)


def _finite(value: float) -> float:
    """Map non-finite floats to JSON-safe stand-ins (Postgres rejects inf/NaN).

    +inf → a large finite value (the profit-factor 'only winners' convention);
    NaN / -inf → 0.0.
    """
    if math.isfinite(value):
        return value
    return _PROFIT_FACTOR_INF if value > 0 else 0.0


def _metrics_to_dict(metrics: Metrics) -> dict[str, Any]:
    """Serialize a Metrics dataclass to a JSON-safe dict (no inf/nan)."""
    data = asdict(metrics)
    data["profit_factor"] = _finite(data["profit_factor"])
    return data


def _summary_to_dict(summary: DistributionSummary) -> dict[str, Any]:
    """Serialize the distribution summary, sanitizing non-finite floats.

    ``best``/``median``/``worst``/the gap can be non-finite when the objective is
    profit_factor and a combination has only winners — sanitize so the JSON column
    stays valid.
    """
    data = asdict(summary)
    for key in ("best", "median", "worst", "in_sample_vs_out_sample_gap"):
        data[key] = _finite(data[key])
    return data


def _combination_to_dict(result: CombinationResult) -> dict[str, Any]:
    return {
        "params": result.params,
        "in_sample": _metrics_to_dict(result.in_sample),
        "out_sample": (
            _metrics_to_dict(result.out_sample) if result.out_sample is not None else None
        ),
        "num_trades_in": result.num_trades_in,
        "num_trades_out": result.num_trades_out,
    }


def _split_to_dict(split: SplitResult) -> dict[str, Any]:
    return {
        "train_start": split.train_start,
        "train_end": split.train_end,
        "test_start": split.test_start,
        "test_end": split.test_end,
        "chosen_params": split.chosen_params,
        "in_sample": _metrics_to_dict(split.in_sample),
        "out_sample": _metrics_to_dict(split.out_sample),
        "baseline_out_sample": _metrics_to_dict(split.baseline_out_sample),
        "num_trades_in": split.num_trades_in,
        "num_trades_out": split.num_trades_out,
    }


def build_sweep_run(req: SweepRequest, featured: pd.DataFrame) -> EvaluationRun:
    """Run the sweep over *featured* and build the (unpersisted) EvaluationRun."""
    results, summary = run_sweep(
        featured,
        symbol=req.symbol,
        strategy_name=req.strategy_name,
        param_grid=req.param_grid,
        run_kwargs=_run_kwargs(req),
        objective=req.objective,
    )
    payload = {
        "summary": _summary_to_dict(summary),
        "n_combinations": len(results),
        "caveat": _CAVEAT,
        "combinations": [_combination_to_dict(r) for r in results],
    }
    return EvaluationRun(
        kind="sweep",
        symbol=req.symbol,
        strategy_name=req.strategy_name,
        status="completed",
        objective=req.objective,
        config=req.model_dump(),
        results=payload,
        finished_at=datetime.now(UTC),
    )


def build_walk_forward_run(
    req: WalkForwardRequest, featured: pd.DataFrame
) -> EvaluationRun:
    """Run walk-forward over *featured* and build the (unpersisted) EvaluationRun."""
    splits = generate_splits(
        len(featured),
        scheme=req.scheme,
        in_sample_size=req.in_sample_size,
        out_sample_size=req.out_sample_size,
        step=req.step,
    )
    wf: WalkForwardResult = run_walk_forward(
        featured,
        symbol=req.symbol,
        strategy_name=req.strategy_name,
        param_grid=req.param_grid,
        splits=splits,
        run_kwargs=_run_kwargs(req),
        objective=req.objective,
        baseline_strategy_name=req.baseline_strategy_name,
        baseline_params=req.baseline_params,
    )
    payload = {
        "summary": _summary_to_dict(wf.summary) if wf.summary is not None else {},
        "n_combinations": count_combinations(req.param_grid),
        "caveat": _CAVEAT,
        "splits": [_split_to_dict(s) for s in wf.splits],
    }
    return EvaluationRun(
        kind="walk_forward",
        symbol=req.symbol,
        strategy_name=req.strategy_name,
        status="completed",
        objective=req.objective,
        config=req.model_dump(),
        results=payload,
        finished_at=datetime.now(UTC),
    )


def _persist(db: Session, run: EvaluationRun) -> EvaluationRun:
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_sweep_pipeline(req: SweepRequest, db: Session) -> EvaluationRun:
    """Validate → load+feature → sweep → persist. Returns the saved run."""
    validate_and_expand(req)  # guard + strategy validation before any load
    featured = load_and_feature_frame(req.symbol, req.csv_path, db)
    run = _persist(db, build_sweep_run(req, featured))
    log.info(
        "Evaluation sweep %s persisted: %d combinations on %s.",
        run.id, len(run.results.get("combinations", [])), req.symbol,
    )
    return run


def run_walk_forward_pipeline(req: WalkForwardRequest, db: Session) -> EvaluationRun:
    """Validate → load+feature → walk-forward → persist. Returns the saved run."""
    validate_and_expand(req)
    featured = load_and_feature_frame(req.symbol, req.csv_path, db)
    run = _persist(db, build_walk_forward_run(req, featured))
    log.info(
        "Evaluation walk-forward %s persisted: %d splits on %s.",
        run.id, len(run.results.get("splits", [])), req.symbol,
    )
    return run
