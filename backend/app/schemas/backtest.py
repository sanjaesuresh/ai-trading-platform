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
