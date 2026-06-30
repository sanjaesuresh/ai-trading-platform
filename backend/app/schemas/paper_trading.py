"""Request/response contracts for the paper-trading API (Phase 3, M4).

Validated, bounded inputs (a bad symbol list, capital, or risk limit is a clean
4xx, never a 500) and JSON-safe response shapes for the deployment lifecycle, the
portfolio dashboard, and the live-vs-backtest comparison. Every read carries the
simulated-only disclaimer the product requires.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DISCLAIMER = (
    "Simulated paper trading against Alpaca's paper endpoint. No real money is "
    "traded. Results are not financial advice and do not imply real or future "
    "returns."
)

RunPhase = Literal["submit", "reconcile", "both"]


class DeploymentRiskConfig(BaseModel):
    """The portfolio sizing / cost / risk-limit knobs (everything except capital).

    Defaults follow the Phase 3 plan §3.3: no leverage (gross cap 1.0), ≤5 open
    positions, a −20% portfolio drawdown kill. Bounds reject leverage, negative
    costs, and nonsensical fractions before anything is persisted.
    """

    model_config = ConfigDict(extra="forbid")

    fee_bps: float = Field(default=5.0, ge=0.0, le=1000.0)
    slippage_bps: float = Field(default=5.0, ge=0.0, le=1000.0)
    target_vol: float | None = Field(default=None, gt=0.0, le=5.0)
    vol_lookback: int = Field(default=20, ge=2, le=512)
    max_position_pct: float = Field(default=0.95, gt=0.0, le=1.0)
    # Cash account, no leverage: gross exposure capped at 100% of equity.
    gross_exposure_cap: float = Field(default=1.0, gt=0.0, le=1.0)
    max_open_positions: int = Field(default=5, ge=1, le=100)
    per_order_notional_cap: float | None = Field(default=None, gt=0.0)
    stop_loss_pct: float | None = Field(default=None, gt=0.0, lt=1.0)
    take_profit_pct: float | None = Field(default=None, gt=0.0, le=10.0)
    max_drawdown_cutoff_pct: float | None = Field(default=0.20, gt=0.0, lt=1.0)


class DeploymentCreateRequest(BaseModel):
    """Create a paper-trading deployment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    strategy_name: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)
    symbols: list[str] = Field(min_length=1, max_length=50)
    starting_capital: float = Field(gt=0.0)
    config: DeploymentRiskConfig = Field(default_factory=DeploymentRiskConfig)
    enabled: bool = True


class DeploymentUpdateRequest(BaseModel):
    """Patch a deployment's definition. Only provided fields change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    params: dict | None = None
    symbols: list[str] | None = Field(default=None, min_length=1, max_length=50)
    starting_capital: float | None = Field(default=None, gt=0.0)
    config: DeploymentRiskConfig | None = None


class EnableRequest(BaseModel):
    enabled: bool


class RunTriggerRequest(BaseModel):
    """Trigger a paper run. ``phase`` defaults to a full run-now."""

    trading_day: date | None = None
    phase: RunPhase = "both"


class RunTriggerResponse(BaseModel):
    job_id: str | None
    status: str
    deployment_id: int
    phase: RunPhase
    trading_day: date | None


class KillSwitchRequest(BaseModel):
    active: bool
    reason: str = ""


class KillSwitchStatus(BaseModel):
    active: bool
    reason: str


# --- Read models ------------------------------------------------------------


class DeploymentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    strategy_name: str
    symbols: list[str]
    starting_capital: float
    enabled: bool
    status: str
    halt_reason: str | None
    created_at: datetime
    updated_at: datetime


class DeploymentDetail(DeploymentSummary):
    params: dict
    config: dict


class PortfolioSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trading_day: date
    equity: float
    cash: float
    position_value: float
    gross_exposure_pct: float
    drawdown_pct: float
    peak_equity: float
    num_positions: int


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trading_day: date
    symbol: str
    quantity: float
    avg_entry_price: float
    market_value: float
    current_price: float


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trading_day: date
    symbol: str
    side: str
    intended_quantity: float
    intended_notional: float
    reference_price: float
    status: str
    filled_quantity: float
    reason: str
    submitted_at: datetime | None


class FillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trading_day: date
    symbol: str
    side: str
    quantity: float
    price: float
    modeled_reference_price: float
    slippage_delta: float
    filled_at: datetime | None


class ReconOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trading_day: date
    kind: str
    symbol: str | None
    detail: str
    created_at: datetime


class SlippageSummary(BaseModel):
    """The implementation-shortfall distribution (realized fill minus modeled
    open, cost-signed) — the quantified residual backtest↔paper gap."""

    count: int
    mean: float
    median: float
    min: float
    max: float


class PortfolioView(BaseModel):
    """The paper-trading dashboard payload for one deployment."""

    deployment: DeploymentDetail
    equity_curve: list[PortfolioSnapshotOut]
    positions: list[PositionOut]
    orders: list[OrderOut]
    fills: list[FillOut]
    reconciliations: list[ReconOut]
    slippage: SlippageSummary
    global_kill: KillSwitchStatus
    disclaimer: str = DISCLAIMER


class MetricsOut(BaseModel):
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    win_rate: float
    profit_factor: float
    num_round_trips: int


class ComparisonView(BaseModel):
    """The live paper results beside the deployment's backtested expectation on the
    same allocation logic, plus the measured residual fill-model gap."""

    deployment_id: int
    backtest_expectation: MetricsOut | None
    live_equity_curve: list[PortfolioSnapshotOut]
    slippage: SlippageSummary
    caveat: str = (
        "The backtest models a next-open fill; paper fills against real quotes "
        "and does not simulate dividends, market impact, latency, or queue "
        "position. The slippage distribution is the measured backtest↔paper gap; "
        "the paper↔live gap is larger and not modeled. Simulated only."
    )
    disclaimer: str = DISCLAIMER
