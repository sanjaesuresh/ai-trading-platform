"""Metrics contract returned to the frontend."""

from __future__ import annotations

from pydantic import BaseModel


class MetricsSchema(BaseModel):
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    win_rate: float
    profit_factor: float
    num_round_trips: int
    num_fills: int
    avg_win: float
    avg_loss: float
    avg_holding_days: float
    exposure_pct: float
