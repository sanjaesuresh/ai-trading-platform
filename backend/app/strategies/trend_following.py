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
_REQUIRED = ["sma_20", "sma_50", "ema_20", "rsi_14", "macd", "macd_signal", "volume_ma_20"]

_RSI_BUY_LOW = 45.0
_RSI_BUY_HIGH = 75.0
_RSI_SELL_HIGH = 80.0
_CONFIDENCE_BASE = 0.5
_CONFIDENCE_STEP = 0.1
_CONFIDENCE_CAP = 0.95


class TrendFollowingStrategy(BaseStrategy):
    name = "trend_following"

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        symbol = str(row.get("symbol", ""))
        ts = row["timestamp"]

        if any(pd.isna(row.get(col)) for col in _REQUIRED):
            return StrategyDecision(
                timestamp=ts,
                symbol=symbol,
                action=StrategySignal.HOLD,
                confidence=0.0,
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
            "RSI in [45,75]": _RSI_BUY_LOW <= rsi <= _RSI_BUY_HIGH,
            "MACD > signal": macd > macd_signal,
            "volume > avg": volume > volume_ma,
        }
        # Bearish conditions (any triggers a sell).
        bear = {
            "SMA-20 < SMA-50": sma_20 < sma_50,
            "close < SMA-20": close < sma_20,
            "RSI > 80": rsi > _RSI_SELL_HIGH,
            "MACD < signal": macd < macd_signal,
        }

        bear_fired = [name for name, hit in bear.items() if hit]

        if all(bull.values()):
            confirms = sum(bull.values())
            confidence = min(_CONFIDENCE_CAP, _CONFIDENCE_BASE + _CONFIDENCE_STEP * confirms)
            reason = "Buy: " + ", ".join(name for name in bull)
            return StrategyDecision(
                timestamp=ts,
                symbol=symbol,
                action=StrategySignal.BUY,
                confidence=confidence,
                reason=reason,
                metadata={"bull_conditions": list(bull)},
            )

        if bear_fired:
            confidence = min(_CONFIDENCE_CAP, _CONFIDENCE_BASE + _CONFIDENCE_STEP * len(bear_fired))
            reason = "Sell: " + ", ".join(bear_fired)
            return StrategyDecision(
                timestamp=ts,
                symbol=symbol,
                action=StrategySignal.SELL,
                confidence=confidence,
                reason=reason,
                metadata={"bear_conditions": bear_fired},
            )

        return StrategyDecision(
            timestamp=ts,
            symbol=symbol,
            action=StrategySignal.HOLD,
            confidence=_CONFIDENCE_BASE,
            reason="No clear trend signal; holding.",
        )
