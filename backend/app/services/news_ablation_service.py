"""News-ablation evaluation runner: DB inputs → ablation harness → stored result.

Rebuilds the ablation inputs from the database (raw OHLCV per symbol, each
symbol's annotated news, and the honest billed annotation spend), runs
``run_news_ablation`` (§6), and stores the result on the EvaluationRun row so the
M7 UI can render the price-only vs price-plus-news comparison.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.data.db_loader import orm_rows_to_frame, query_market_data
from app.llm.db import annotation_cost_for_symbols, load_symbol_annotations
from app.llm.prompt import PROMPT_VERSION
from app.ml.ablation import run_news_ablation
from app.ml.features import FeatureLabelSpec
from app.ml.training import TrainingConfig
from app.models_db.evaluation_run import EvaluationRun
from app.schemas.news import NewsAblationRequest
from app.services.ml_service import sanitize_result_dict

log = get_logger(__name__)


def run_news_ablation_evaluation(db: Session, run: EvaluationRun) -> EvaluationRun:
    """Execute a news ablation in place on the run row (dispatched by kind)."""
    req = NewsAblationRequest(**run.config)

    ohlcv_frames = {
        symbol: orm_rows_to_frame(query_market_data(db, symbol))
        for symbol in req.symbols
    }
    annotations: dict[str, pd.DataFrame | None] = {
        symbol: load_symbol_annotations(db, symbol, PROMPT_VERSION)
        for symbol in req.symbols
    }
    annotation_cost = annotation_cost_for_symbols(db, req.symbols, PROMPT_VERSION)

    training_config = TrainingConfig(
        spec=FeatureLabelSpec(horizon=req.horizon, deadband=req.deadband),
        seed=req.seed,
    )
    result = run_news_ablation(
        ohlcv_frames,
        annotations,
        eval_symbol=req.eval_symbol,
        annotation_cost_usd=annotation_cost,
        n_news_configs_tried=req.n_news_configs_tried,
        training_config=training_config,
        news_embargo=req.news_embargo,
        relevance_threshold=req.relevance_threshold,
        horizon=req.horizon,
        in_sample_dates=req.in_sample_dates,
        out_sample_dates=req.out_sample_dates,
        step_dates=req.step_dates,
        fee_bps=req.fee_bps,
        slippage_bps=req.slippage_bps,
        initial_capital=req.initial_capital,
        mc_runs=req.mc_runs,
        seed=req.seed,
    )

    run.results = sanitize_result_dict(result.to_dict())
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    log.info(
        "News ablation run %s completed (eval_symbol=%s, beats_price_only=%s, cost=$%.4f).",
        run.id, req.eval_symbol, result.incremental.beats_price_only, annotation_cost,
    )
    return run
