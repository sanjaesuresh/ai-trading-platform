"""Backtest run endpoints: run, list, detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models_db.backtest_run import BacktestRun
from app.schemas.backtest import RunDetail, RunRequest, RunSummary
from app.services.backtest_service import (
    BacktestRequestError,
    build_run_detail,
    run_backtest_pipeline,
)

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("/run", response_model=RunSummary, status_code=status.HTTP_201_CREATED)
def run_backtest_endpoint(req: RunRequest, db: Session = Depends(get_db)) -> RunSummary:
    """Run the trend-following backtest on a CSV and persist the result."""
    try:
        run = run_backtest_pipeline(req, db)
    except BacktestRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": exc.message, "errors": exc.details},
        ) from exc
    return RunSummary.model_validate(run)


@router.get("", response_model=list[RunSummary])
def list_backtests(db: Session = Depends(get_db)) -> list[RunSummary]:
    """Return run summaries, newest first."""
    runs = db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc())).all()
    return [RunSummary.model_validate(r) for r in runs]


@router.get("/{run_id}", response_model=RunDetail)
def get_backtest(run_id: int, db: Session = Depends(get_db)) -> RunDetail:
    """Return the full detail of one run, or 404 if unknown."""
    run = db.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found."
        )
    return build_run_detail(run)
