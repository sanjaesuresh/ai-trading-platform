"""ML pipeline routes (Phase 4 M4).

- POST /ml/models                → train + register one model (synchronous).
- GET  /ml/models                → list registered models (DB).
- GET  /ml/models/{model_id}     → detail for one model.
- POST /ml/evaluations/walk-forward → enqueue walk-forward evaluation (async).
- POST /ml/evaluations/backtest     → enqueue pinned-model backtest (async).
- GET  /ml/evaluations/{id}         → poll evaluation detail.

All results are simulated — not financial advice.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.jobs.queue import enqueue
from app.jobs.tasks import ML_TASK_NAME
from app.models_db.evaluation_run import EvaluationRun
from app.schemas.ml import (
    MLBacktestRequest,
    MLEvaluationDetail,
    MLEvaluationSummary,
    MLModelDetail,
    MLModelSummary,
    MLTrainRequest,
    MLWalkForwardRequest,
)
from app.services.backtest_service import BacktestRequestError
from app.services.ml_service import (
    create_queued_ml_run,
    get_ml_model,
    list_ml_models,
    mark_failed,
    train_and_register,
)

router = APIRouter(prefix="/ml", tags=["ml"])


def _bad_request(exc: BacktestRequestError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"message": exc.message, "errors": exc.details},
    )


async def _enqueue_or_fail(run: EvaluationRun, db: Session) -> None:
    """Enqueue the ML worker job; if the queue is unreachable, mark the row failed.

    Mirrors the same guard in evaluation.py — a row stranded in ``queued``
    forever is worse than surfacing a 503.
    """
    try:
        await enqueue(ML_TASK_NAME, evaluation_run_id=run.id)
    except Exception as exc:  # noqa: BLE001
        mark_failed(db, run, f"Failed to enqueue ML job: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Could not enqueue the ML evaluation job; the queue may be unavailable.",
                "errors": [],
            },
        ) from exc


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------


@router.post("/models", response_model=MLModelSummary, status_code=status.HTTP_201_CREATED)
def create_ml_model(
    req: MLTrainRequest, db: Session = Depends(get_db)
) -> MLModelSummary:
    """Train and register one ML model. Results are simulated — not financial advice."""
    try:
        row = train_and_register(db, req)
    except BacktestRequestError as exc:
        raise _bad_request(exc) from exc
    return MLModelSummary.model_validate(row)


@router.get("/models", response_model=list[MLModelSummary])
def list_models_endpoint(db: Session = Depends(get_db)) -> list[MLModelSummary]:
    """Return all registered models, newest-first by train_end."""
    rows = list_ml_models(db)
    return [MLModelSummary.model_validate(r) for r in rows]


@router.get("/models/{model_id}", response_model=MLModelDetail)
def get_model_endpoint(model_id: str, db: Session = Depends(get_db)) -> MLModelDetail:
    """Return one registered model by model_id, or 404 if unknown."""
    row = get_ml_model(db, model_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ML model '{model_id}' not found.",
        )
    return MLModelDetail.model_validate(row)


# ---------------------------------------------------------------------------
# ML evaluations
# ---------------------------------------------------------------------------


@router.post(
    "/evaluations/walk-forward",
    response_model=MLEvaluationSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_walk_forward(
    req: MLWalkForwardRequest, db: Session = Depends(get_db)
) -> MLEvaluationSummary:
    """Queue a walk-forward ML evaluation; poll GET /ml/evaluations/{id}."""
    run = create_queued_ml_run(req, kind="ml_walk_forward", db=db)
    await _enqueue_or_fail(run, db)
    return MLEvaluationSummary.model_validate(run)


@router.post(
    "/evaluations/backtest",
    response_model=MLEvaluationSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_backtest(
    req: MLBacktestRequest, db: Session = Depends(get_db)
) -> MLEvaluationSummary:
    """Queue a pinned-model ML backtest; poll GET /ml/evaluations/{id}."""
    run = create_queued_ml_run(req, kind="ml_backtest", db=db)
    await _enqueue_or_fail(run, db)
    return MLEvaluationSummary.model_validate(run)


@router.get("/evaluations/{evaluation_id}", response_model=MLEvaluationDetail)
def get_ml_evaluation(
    evaluation_id: int, db: Session = Depends(get_db)
) -> MLEvaluationDetail:
    """Return the full detail of one ML evaluation run, or 404 if unknown."""
    run = db.get(EvaluationRun, evaluation_id)
    if run is None or run.kind not in ("ml_walk_forward", "ml_backtest"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ML evaluation {evaluation_id} not found.",
        )
    return MLEvaluationDetail.model_validate(run)
