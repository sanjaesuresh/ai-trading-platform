"""Evaluation endpoints: enqueue a sweep or walk-forward, list, detail.

By default a sweep / walk-forward is enqueued onto the background queue (202,
``queued``) and polled via ``GET /evaluations/{id}`` — the heavy work runs on the
worker, not in the request. The ``/sync`` sub-paths keep M5's inline behavior
(201, ``completed``) for small grids and tests. Validation runs at enqueue time,
so an oversized/invalid grid is still a clean 400 before anything is queued.

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
from app.jobs.queue import enqueue
from app.jobs.tasks import EVALUATION_TASK_NAME
from app.models_db.evaluation_run import EvaluationRun
from app.schemas.evaluation import (
    EvaluationDetail,
    EvaluationSummary,
    SweepRequest,
    WalkForwardRequest,
)
from app.services.backtest_service import BacktestRequestError
from app.services.evaluation_service import (
    create_queued_sweep_run,
    create_queued_walk_forward_run,
    mark_failed,
    run_sweep_pipeline,
    run_walk_forward_pipeline,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def _bad_request(exc: BacktestRequestError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"message": exc.message, "errors": exc.details},
    )


async def _enqueue_or_fail(run: EvaluationRun, db: Session) -> None:
    """Enqueue the worker job; if the queue is unreachable, mark the row failed.

    The row is committed as ``queued`` before this call, so a queue outage would
    otherwise strand it forever. Flipping it to ``failed`` keeps it visible and
    pollable instead, and surfaces a clean 503.
    """
    try:
        await enqueue(EVALUATION_TASK_NAME, evaluation_run_id=run.id)
    except Exception as exc:  # noqa: BLE001 — any queue error must not strand the row
        mark_failed(db, run, f"Failed to enqueue evaluation job: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Could not enqueue the evaluation job; the queue may be unavailable.",
                "errors": [],
            },
        ) from exc


@router.post("/sweep", response_model=EvaluationSummary, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_sweep(
    req: SweepRequest, db: Session = Depends(get_db)
) -> EvaluationSummary:
    """Queue a parameter sweep; poll GET /evaluations/{id}. Results are simulated."""
    try:
        run = create_queued_sweep_run(req, db)
    except BacktestRequestError as exc:
        raise _bad_request(exc) from exc
    # Row exists in `queued` before the job is enqueued, so it is always pollable.
    await _enqueue_or_fail(run, db)
    return EvaluationSummary.model_validate(run)


@router.post(
    "/walk-forward",
    response_model=EvaluationSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_walk_forward(
    req: WalkForwardRequest, db: Session = Depends(get_db)
) -> EvaluationSummary:
    """Queue an out-of-sample walk-forward evaluation; poll GET /evaluations/{id}."""
    try:
        run = create_queued_walk_forward_run(req, db)
    except BacktestRequestError as exc:
        raise _bad_request(exc) from exc
    await _enqueue_or_fail(run, db)
    return EvaluationSummary.model_validate(run)


@router.post(
    "/sweep/sync", response_model=EvaluationSummary, status_code=status.HTTP_201_CREATED
)
def run_sweep_sync(
    req: SweepRequest, db: Session = Depends(get_db)
) -> EvaluationSummary:
    """Run a sweep inline and persist it (M5 behavior, for small grids)."""
    try:
        run = run_sweep_pipeline(req, db)
    except BacktestRequestError as exc:
        raise _bad_request(exc) from exc
    return EvaluationSummary.model_validate(run)


@router.post(
    "/walk-forward/sync",
    response_model=EvaluationSummary,
    status_code=status.HTTP_201_CREATED,
)
def run_walk_forward_sync(
    req: WalkForwardRequest, db: Session = Depends(get_db)
) -> EvaluationSummary:
    """Run a walk-forward evaluation inline and persist it (M5 behavior)."""
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
