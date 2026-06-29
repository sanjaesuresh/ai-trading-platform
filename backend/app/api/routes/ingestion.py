"""Ingestion endpoints: trigger a background ingest, and read the audit trail.

Triggering enqueues ``ingest_task`` through the queue seam and returns 202 with
the job id — the work runs on the worker, not in the request. The audit endpoints
read ``IngestionRun`` rows so a run's outcome (rows written, status, error) is
inspectable. Simulated research tool — not financial advice.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.jobs.queue import enqueue
from app.jobs.tasks import INGEST_TASK_NAME
from app.models_db.ingestion_run import IngestionRun
from app.schemas.ingestion import (
    IngestionEnqueueResponse,
    IngestionRunRequest,
    IngestionRunSummary,
)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

_VALID_MODES = ("backfill", "incremental")


@router.post(
    "/run",
    response_model=IngestionEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_ingestion(req: IngestionRunRequest) -> IngestionEnqueueResponse:
    """Enqueue a backfill or incremental ingest; returns the queued job id."""
    if req.mode not in _VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": (
                    f"Unknown ingest mode {req.mode!r}; "
                    f"expected one of {list(_VALID_MODES)}."
                ),
                "errors": [],
            },
        )
    job_id = await enqueue(INGEST_TASK_NAME, mode=req.mode, symbols=req.symbols)
    return IngestionEnqueueResponse(
        job_id=job_id, status="queued", mode=req.mode, symbols=req.symbols
    )


@router.get("", response_model=list[IngestionRunSummary])
def list_ingestion_runs(db: Session = Depends(get_db)) -> list[IngestionRunSummary]:
    """Return ingestion audit rows, newest first."""
    runs = db.scalars(select(IngestionRun).order_by(IngestionRun.id.desc())).all()
    return [IngestionRunSummary.model_validate(r) for r in runs]


@router.get("/{ingestion_id}", response_model=IngestionRunSummary)
def get_ingestion_run(
    ingestion_id: int, db: Session = Depends(get_db)
) -> IngestionRunSummary:
    """Return one ingestion audit row, or 404 if unknown."""
    run = db.get(IngestionRun, ingestion_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingestion run {ingestion_id} not found.",
        )
    return IngestionRunSummary.model_validate(run)
