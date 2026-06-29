"""Request/response contracts for backtest runs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.metrics import MetricsSchema
from app.schemas.trade import EquityPointSchema, TradeSchema


class RunRequest(BaseModel):
    """Inputs to a backtest run.

    Data source — exactly one of:

    * **CSV mode** — provide ``csv_path`` (path under the allowed data
      directory).  ``symbol`` is used as the run label only.
    * **DB mode** — omit ``csv_path`` (leave it ``None``).  ``symbol`` is used
      to look up stored, adjusted bars from the ``market_data`` table.

    Providing an empty string for ``csv_path`` is rejected (``min_length=1``).
    Providing no ``csv_path`` without any stored bars for ``symbol`` will raise
    a ``BacktestRequestError`` at run time.
    """

    symbol: str = Field(min_length=1, max_length=32)
    csv_path: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Path under the allowed data directory (CSV mode). "
            "Omit to read from the database using ``symbol`` (DB mode)."
        ),
    )
    initial_capital: float = Field(default=100_000.0, gt=0)
    fee_bps: float = Field(default=5.0, ge=0, le=1_000)
    slippage_bps: float = Field(default=5.0, ge=0, le=1_000)
    max_position_pct: float = Field(default=0.95, gt=0, le=1.0)
    # --- Phase 2 risk / sizing params (all optional, None = disabled) ---
    target_vol: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Target annualised volatility for position sizing, e.g. 0.15 for 15 %. "
            "None disables volatility targeting; the engine uses max_position_pct flat."
        ),
    )
    vol_lookback: int = Field(
        default=20,
        ge=2,
        description=(
            "Number of daily returns used to estimate realised volatility "
            "when target_vol is set.  Ignored when target_vol is None."
        ),
    )
    stop_loss_pct: float | None = Field(
        default=None,
        gt=0,
        le=1.0,
        description=(
            "Stop-loss threshold as a fraction of the entry price, e.g. 0.05 for 5 %. "
            "The exit is evaluated at bar-N close and filled at bar N+1 open. "
            "None disables."
        ),
    )
    take_profit_pct: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Take-profit threshold as a fraction of the entry price, e.g. 0.20 for 20 %. "
            "The exit is evaluated at bar-N close and filled at bar N+1 open. "
            "None disables."
        ),
    )
    max_drawdown_cutoff_pct: float | None = Field(
        default=None,
        gt=0,
        le=1.0,
        description=(
            "Max-drawdown circuit breaker.  When equity draws down this fraction from "
            "its running peak the engine flattens the position and halts new entries "
            "for the rest of the run.  None disables."
        ),
    )


class RunSummary(BaseModel):
    """One row in the runs list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    strategy_name: str
    status: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    num_trades: int
    created_at: datetime


class RunDetail(BaseModel):
    """Full run detail: summary plus config, metrics, equity curve, trades."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    strategy_name: str
    status: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    num_trades: int
    created_at: datetime
    config: dict
    metrics: MetricsSchema
    equity_curve: list[EquityPointSchema]
    trades: list[TradeSchema]
