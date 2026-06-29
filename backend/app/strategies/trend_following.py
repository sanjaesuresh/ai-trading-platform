"""Baseline rule-based trend-following strategy.

This is a reference baseline to prove the plumbing, not a profitable system.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)

# Required indicator columns; if any is NaN the strategy abstains (HOLD).
_REQUIRED = ["sma_20", "sma_50", "rsi_14", "macd", "macd_signal", "volume_ma_20"]

# Conventional, untuned RSI bands — the defaults that reproduce Phase 1 behaviour.
_RSI_BUY_LOW = 45.0
_RSI_BUY_HIGH = 75.0
_RSI_SELL_HIGH = 80.0


class TrendFollowingStrategy(BaseStrategy):
    name = "trend_following"

    def __init__(
        self,
        rsi_buy_low: float = _RSI_BUY_LOW,
        rsi_buy_high: float = _RSI_BUY_HIGH,
        rsi_sell_high: float = _RSI_SELL_HIGH,
    ) -> None:
        """Tunable RSI bands. Defaults reproduce the Phase 1 baseline exactly."""
        self.rsi_buy_low = rsi_buy_low
        self.rsi_buy_high = rsi_buy_high
        self.rsi_sell_high = rsi_sell_high

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
