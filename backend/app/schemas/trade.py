"""Trade and equity-curve contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TradeSchema(BaseModel):
    symbol: str
    side: str
    timestamp: datetime
    price: float
    quantity: float
    gross_value: float
    fee: float
    slippage: float
    cash_after: float
    position_after: float
    equity_after: float
    reason: str


class EquityPointSchema(BaseModel):
    timestamp: datetime
    equity: float
    cash: float
    position_value: float
