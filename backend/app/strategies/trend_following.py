"""Baseline rule-based trend-following strategy.

This is a reference baseline to prove the plumbing, not a profitable system.
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

# Required indicator columns; if any is NaN the strategy abstains (HOLD).
_REQUIRED = ["sma_20", "sma_50", "rsi_14", "macd", "macd_signal", "volume_ma_20"]


class TrendFollowingParams(BaseModel):
    """Tunable RSI bands for trend-following. Defaults = Phase 1 baseline.

    The single source of truth for this strategy's defaults and validation: the
    constructor and the registry both go through this model, so direct
    construction is validated too.
    """

    model_config = ConfigDict(extra="forbid")

    rsi_buy_low: float = Field(default=45.0, ge=0.0, le=100.0)
    rsi_buy_high: float = Field(default=75.0, ge=0.0, le=100.0)
    rsi_sell_high: float = Field(default=80.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _bands_ordered(self) -> TrendFollowingParams:
        if self.rsi_buy_low > self.rsi_buy_high:
            raise ValueError("rsi_buy_low must be <= rsi_buy_high.")
        return self


_DEFAULTS = TrendFollowingParams()


class TrendFollowingStrategy(BaseStrategy):
    name = "trend_following"

    def __init__(
        self,
        rsi_buy_low: float = _DEFAULTS.rsi_buy_low,
        rsi_buy_high: float = _DEFAULTS.rsi_buy_high,
        rsi_sell_high: float = _DEFAULTS.rsi_sell_high,
    ) -> None:
        """Tunable RSI bands. Defaults reproduce the Phase 1 baseline exactly."""
        params = TrendFollowingParams(
            rsi_buy_low=rsi_buy_low,
            rsi_buy_high=rsi_buy_high,
            rsi_sell_high=rsi_sell_high,
        )
        self.rsi_buy_low = params.rsi_buy_low
        self.rsi_buy_high = params.rsi_buy_high
        self.rsi_sell_high = params.rsi_sell_high

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        if any(pd.isna(row.get(col)) for col in _REQUIRED):
            return StrategyDecision(
                action=StrategySignal.HOLD,
                reason="Indicators not yet warmed up; holding.",
            )

        close = float(row["close"])
        sma_20 = float(row["sma_20"])
        sma_50 = float(row["sma_50"])
        rsi = float(row["rsi_14"])
        macd = float(row["macd"])
        macd_signal = float(row["macd_signal"])
        volume = float(row["volume"])
        volume_ma = float(row["volume_ma_20"])

        # Bullish conditions (all must hold to buy).
        bull = {
            "SMA-20 > SMA-50": sma_20 > sma_50,
            "close > SMA-20": close > sma_20,
            f"RSI in [{self.rsi_buy_low:g},{self.rsi_buy_high:g}]": (
                self.rsi_buy_low <= rsi <= self.rsi_buy_high
            ),
            "MACD > signal": macd > macd_signal,
            "volume > avg": volume > volume_ma,
        }
        # Bearish conditions (any triggers a sell).
        bear = {
            "SMA-20 < SMA-50": sma_20 < sma_50,
            "close < SMA-20": close < sma_20,
            f"RSI > {self.rsi_sell_high:g}": rsi > self.rsi_sell_high,
            "MACD < signal": macd < macd_signal,
        }

        bear_fired = [name for name, hit in bear.items() if hit]

        if all(bull.values()):
            reason = "Buy: " + ", ".join(name for name in bull)
            return StrategyDecision(action=StrategySignal.BUY, reason=reason)

        if bear_fired:
            reason = "Sell: " + ", ".join(bear_fired)
            return StrategyDecision(action=StrategySignal.SELL, reason=reason)

        return StrategyDecision(
            action=StrategySignal.HOLD,
            reason="No clear trend signal; holding.",
        )
