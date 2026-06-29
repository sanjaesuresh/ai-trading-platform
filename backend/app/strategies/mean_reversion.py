"""Rule-based mean-reversion strategy (Bollinger-style lower band).

A second baseline that proves the strategy registry and gives M5 something to
compare, net of fees, against trend-following. Like trend-following it is a
reference baseline, **not** a profitable system.

Logic, computed only from bar N's close and indicators known at bar N's close
(the engine fills at bar N+1's open — no look-ahead):

* **Buy** when the close drops below the lower band
  ``SMA_20 - entry_std * std_20`` (oversold relative to its mean).
* **Sell** when the close reverts back up to the exit band
  ``SMA_20 - exit_std * std_20`` (mean reversion captured; ``exit_std=0`` exits
  at the mean).
* **Hold** otherwise.

Long-only, one position at a time — position management (no double-buy, no sell
while flat, next-bar-open fills, final-bar force-close) is the engine's job, so
this mirrors the trend-following decision shape exactly.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)

# Indicators this strategy reads; if any is NaN (warm-up) it abstains (HOLD).
_REQUIRED = ["sma_20", "std_20"]


class MeanReversionParams(BaseModel):
    """Band widths (in rolling-std units) for mean reversion.

    The single source of truth for this strategy's defaults and validation: the
    constructor and the registry both go through this model, so direct
    construction is validated too.
    """

    model_config = ConfigDict(extra="forbid")

    entry_std: float = Field(default=2.0, gt=0.0, le=10.0)
    exit_std: float = Field(default=0.0, ge=0.0, le=10.0)

    @model_validator(mode="after")
    def _entry_below_exit(self) -> MeanReversionParams:
        if self.exit_std >= self.entry_std:
            raise ValueError("exit_std must be < entry_std (exit band above entry band).")
        return self


_DEFAULTS = MeanReversionParams()


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(
        self,
        entry_std: float = _DEFAULTS.entry_std,
        exit_std: float = _DEFAULTS.exit_std,
    ) -> None:
        """Band widths in rolling-std units. Entry below the lower band, exit at
        the mean (``exit_std=0``) or partway back.
        """
        params = MeanReversionParams(entry_std=entry_std, exit_std=exit_std)
        self.entry_std = params.entry_std
        self.exit_std = params.exit_std

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        if any(pd.isna(row.get(col)) for col in _REQUIRED):
            return StrategyDecision(
                action=StrategySignal.HOLD,
                reason="Indicators not yet warmed up; holding.",
            )

        close = float(row["close"])
        sma_20 = float(row["sma_20"])
        std_20 = float(row["std_20"])

        lower_band = sma_20 - self.entry_std * std_20
        exit_band = sma_20 - self.exit_std * std_20

        if close < lower_band:
            return StrategyDecision(
                action=StrategySignal.BUY,
                reason=f"Buy: close {close:.2f} below lower band {lower_band:.2f}",
            )

        if close >= exit_band:
            return StrategyDecision(
                action=StrategySignal.SELL,
                reason=f"Sell: close {close:.2f} reverted to exit band {exit_band:.2f}",
            )

        return StrategyDecision(
            action=StrategySignal.HOLD,
            reason="Between bands; holding.",
        )
