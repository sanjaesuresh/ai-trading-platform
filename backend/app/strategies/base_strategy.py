"""Strategy interface: the typed decision a strategy returns for one bar."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd


class StrategySignal(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Position:
    """The strategy's view of the current position. Long-only in Phase 1."""

    quantity: float = 0.0
    entry_price: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.quantity > 0.0


@dataclass
class StrategyDecision:
    """A typed, explainable decision for a single bar.

    The engine consumes exactly these two fields: ``action`` drives the fill and
    ``reason`` is recorded on the trade for auditability.
    """

    action: StrategySignal
    reason: str


class BaseStrategy(ABC):
    """Abstract base for all strategies."""

    name: str = "base"

    @abstractmethod
    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        """Turn one indicator row plus the current position into a decision."""
