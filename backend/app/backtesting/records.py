"""Neutral value types shared across the backtesting and portfolio layers.

``TradeRecord`` and ``EquityPoint`` are produced by both the single-symbol engine
and the multi-symbol portfolio driver and consumed by the metrics modules. They
live here — not in either driver — so the pure portfolio core and the future live
runner can depend on the shapes without pointing at a concrete driver module.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class TradeRecord:
    symbol: str
    side: str  # "BUY" or "SELL"
    timestamp: pd.Timestamp
    price: float  # effective fill price after slippage
    quantity: float
    gross_value: float
    fee: float
    slippage: float  # slippage cost in currency
    cash_after: float
    position_after: float
    equity_after: float
    reason: str


@dataclass
class EquityPoint:
    timestamp: pd.Timestamp
    equity: float
    cash: float
    position_value: float
