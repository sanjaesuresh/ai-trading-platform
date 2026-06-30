"""Paper-trading endpoints (Phase 3, M4).

Deployment CRUD + enable/disable, a run trigger (enqueued onto the worker), the
portfolio dashboard read, the live-vs-backtest comparison, and the global kill
switch. Validation lives in the Pydantic schemas and the strategy registry, so a
bad request is a clean 4xx, never a 500. Simulated paper trading only — not
financial advice.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.jobs.queue import enqueue
from app.jobs.tasks import PAPER_RUN_TASK_NAME
from app.schemas.paper_trading import (
    ComparisonView,
    DeploymentCreateRequest,
    DeploymentDetail,
    DeploymentSummary,
    DeploymentUpdateRequest,
    EnableRequest,
    FillOut,
    KillSwitchRequest,
    KillSwitchStatus,
    MetricsOut,
    OrderOut,
    PortfolioSnapshotOut,
    PortfolioView,
    PositionOut,
    ReconOut,
    RunTriggerRequest,
    RunTriggerResponse,
    SlippageSummary,
)
from app.services import paper_trading_service as svc
from app.strategies.registry import StrategyParamError, UnknownStrategyError

router = APIRouter(prefix="/paper", tags=["paper-trading"])


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"message": message, "errors": []},
    )


def _require(db: Session, deployment_id: int):
    deployment = svc.get_deployment(db, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment {deployment_id} not found.",
        )
    return deployment


def _finite(value: float) -> float:
    """JSON-safe float: map +inf to a large finite value, nan/-inf to 0.0."""
    if math.isnan(value):
        return 0.0
    if math.isinf(value):
        return 1.0e9 if value > 0 else 0.0
    return value


# --- Deployment CRUD --------------------------------------------------------


@router.post(
    "/deployments", response_model=DeploymentDetail, status_code=status.HTTP_201_CREATED
)
def create_deployment(
    req: DeploymentCreateRequest, db: Session = Depends(get_db)
) -> DeploymentDetail:
    """Create a paper-trading deployment. Enabling it disables any other (one
    enabled deployment per the shared paper account)."""
    try:
        deployment = svc.create_deployment(
            db, name=req.name, strategy_name=req.strategy_name, params=req.params,
            symbols=req.symbols, starting_capital=req.starting_capital,
            config=req.config.model_dump(), enabled=req.enabled,
        )
    except (UnknownStrategyError, StrategyParamError) as exc:
        raise _bad_request(str(exc)) from exc
    return DeploymentDetail.model_validate(deployment)


@router.get("/deployments", response_model=list[DeploymentSummary])
def list_deployments(db: Session = Depends(get_db)) -> list[DeploymentSummary]:
    return [DeploymentSummary.model_validate(d) for d in svc.list_deployments(db)]


@router.get("/deployments/{deployment_id}", response_model=DeploymentDetail)
def get_deployment(
    deployment_id: int, db: Session = Depends(get_db)
) -> DeploymentDetail:
    return DeploymentDetail.model_validate(_require(db, deployment_id))


@router.patch("/deployments/{deployment_id}", response_model=DeploymentDetail)
def update_deployment(
    deployment_id: int, req: DeploymentUpdateRequest, db: Session = Depends(get_db)
) -> DeploymentDetail:
    deployment = _require(db, deployment_id)
    try:
        updated = svc.update_deployment(
            db, deployment, name=req.name, params=req.params, symbols=req.symbols,
            starting_capital=req.starting_capital,
            config=req.config.model_dump() if req.config is not None else None,
        )
    except (UnknownStrategyError, StrategyParamError) as exc:
        raise _bad_request(str(exc)) from exc
    return DeploymentDetail.model_validate(updated)


@router.post("/deployments/{deployment_id}/enable", response_model=DeploymentDetail)
def set_enabled(
    deployment_id: int, req: EnableRequest, db: Session = Depends(get_db)
) -> DeploymentDetail:
    deployment = _require(db, deployment_id)
    return DeploymentDetail.model_validate(svc.set_enabled(db, deployment, req.enabled))


# --- Run trigger ------------------------------------------------------------


@router.post(
    "/deployments/{deployment_id}/run",
    response_model=RunTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_run(
    deployment_id: int, req: RunTriggerRequest
) -> RunTriggerResponse:
    """Enqueue a paper run for this deployment; the worker executes it (it resolves
    the broker and skips cleanly if no Alpaca keys are configured)."""
    trading_day = req.trading_day.isoformat() if req.trading_day else None
    try:
        job_id = await enqueue(
            PAPER_RUN_TASK_NAME, deployment_id=deployment_id,
            trading_day=trading_day, phase=req.phase,
        )
    except Exception as exc:  # noqa: BLE001 — a queue outage must surface, not 500
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Could not enqueue the paper run; the queue may be unavailable.",
                "errors": [],
            },
        ) from exc
    return RunTriggerResponse(
        job_id=job_id, status="queued", deployment_id=deployment_id,
        phase=req.phase, trading_day=req.trading_day,
    )


# --- Dashboard reads --------------------------------------------------------


@router.get("/deployments/{deployment_id}/portfolio", response_model=PortfolioView)
def get_portfolio(
    deployment_id: int, db: Session = Depends(get_db)
) -> PortfolioView:
    deployment = _require(db, deployment_id)
    kill_active, kill_reason = svc.get_global_kill(db)
    return PortfolioView(
        deployment=DeploymentDetail.model_validate(deployment),
        equity_curve=[
            PortfolioSnapshotOut.model_validate(s)
            for s in svc.portfolio_snapshots(db, deployment_id)
        ],
        positions=[
            PositionOut.model_validate(p)
            for p in svc.latest_positions(db, deployment_id)
        ],
        orders=[OrderOut.model_validate(o) for o in svc.recent_orders(db, deployment_id)],
        fills=[FillOut.model_validate(f) for f in svc.recent_fills(db, deployment_id)],
        reconciliations=[
            ReconOut.model_validate(r)
            for r in svc.recent_reconciliations(db, deployment_id)
        ],
        slippage=SlippageSummary.model_validate(svc.slippage_summary(db, deployment_id)),
        global_kill=KillSwitchStatus(active=kill_active, reason=kill_reason),
    )


@router.get("/deployments/{deployment_id}/comparison", response_model=ComparisonView)
def get_comparison(
    deployment_id: int, db: Session = Depends(get_db)
) -> ComparisonView:
    deployment = _require(db, deployment_id)
    metrics = svc.backtest_expectation(db, deployment)
    expectation = None
    if metrics is not None:
        expectation = MetricsOut(
            total_return_pct=_finite(metrics.total_return_pct),
            annualized_return_pct=_finite(metrics.annualized_return_pct),
            max_drawdown_pct=_finite(metrics.max_drawdown_pct),
            sharpe_ratio=_finite(metrics.sharpe_ratio),
            sortino_ratio=_finite(metrics.sortino_ratio),
            win_rate=_finite(metrics.win_rate),
            profit_factor=_finite(metrics.profit_factor),
            num_round_trips=metrics.num_round_trips,
        )
    return ComparisonView(
        deployment_id=deployment_id,
        backtest_expectation=expectation,
        live_equity_curve=[
            PortfolioSnapshotOut.model_validate(s)
            for s in svc.portfolio_snapshots(db, deployment_id)
        ],
        slippage=SlippageSummary.model_validate(svc.slippage_summary(db, deployment_id)),
    )


# --- Global kill switch -----------------------------------------------------


@router.get("/kill-switch", response_model=KillSwitchStatus)
def get_kill_switch(db: Session = Depends(get_db)) -> KillSwitchStatus:
    active, reason = svc.get_global_kill(db)
    return KillSwitchStatus(active=active, reason=reason)


@router.post("/kill-switch", response_model=KillSwitchStatus)
def set_kill_switch(
    req: KillSwitchRequest, db: Session = Depends(get_db)
) -> KillSwitchStatus:
    """Trip or clear the global kill switch; while active it halts all new orders."""
    svc.set_global_kill(db, req.active, req.reason)
    return KillSwitchStatus(active=req.active, reason=req.reason)
