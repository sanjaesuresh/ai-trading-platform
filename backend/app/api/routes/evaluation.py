"""Evaluation endpoints: run a sweep or walk-forward, list, detail.

Results are reported as a full out-of-sample distribution net of fees, never as a
single best cell — the honest-framing requirement lives in the service; this
layer just maps request errors to HTTP 400 with the same ``{message, errors}``
shape ``backtests.py`` uses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models_db.evaluation_run import EvaluationRun
from app.schemas.evaluation import (
    EvaluationDetail,
    EvaluationSummary,
    SweepRequest,
    WalkForwardRequest,
)
from app.services.backtest_service import BacktestRequestError
from app.services.evaluation_service import (
    run_sweep_pipeline,
    run_walk_forward_pipeline,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def _bad_request(exc: BacktestRequestError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"message": exc.message, "errors": exc.details},
    )


@router.post("/sweep", response_model=EvaluationSummary, status_code=status.HTTP_201_CREATED)
def run_sweep_endpoint(
    req: SweepRequest, db: Session = Depends(get_db)
) -> EvaluationSummary:
    """Run a parameter sweep and persist the aggregate. Results are simulated."""
    try:
        run = run_sweep_pipeline(req, db)
    except BacktestRequestError as exc:
        raise _bad_request(exc) from exc
    return EvaluationSummary.model_validate(run)


@router.post(
    "/walk-forward", response_model=EvaluationSummary, status_code=status.HTTP_201_CREATED
)
def run_walk_forward_endpoint(
    req: WalkForwardRequest, db: Session = Depends(get_db)
) -> EvaluationSummary:
    """Run an out-of-sample walk-forward evaluation and persist it. Simulated."""
    try:
        run = run_walk_forward_pipeline(req, db)
    except BacktestRequestError as exc:
        raise _bad_request(exc) from exc
    return EvaluationSummary.model_validate(run)


@router.get("", response_model=list[EvaluationSummary])
def list_evaluations(db: Session = Depends(get_db)) -> list[EvaluationSummary]:
    """Return evaluation summaries, newest first."""
    runs = db.scalars(select(EvaluationRun).order_by(EvaluationRun.id.desc())).all()
    return [EvaluationSummary.model_validate(r) for r in runs]


@router.get("/{evaluation_id}", response_model=EvaluationDetail)
def get_evaluation(evaluation_id: int, db: Session = Depends(get_db)) -> EvaluationDetail:
    """Return the full detail of one evaluation, or 404 if unknown."""
    run = db.get(EvaluationRun, evaluation_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation {evaluation_id} not found.",
        )
    return EvaluationDetail.model_validate(run)
