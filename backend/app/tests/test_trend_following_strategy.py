"""Trend-following strategy: bullish -> buy, bearish -> sell, neutral -> hold."""

from __future__ import annotations

import pandas as pd

from app.strategies.base_strategy import Position, StrategySignal
from app.strategies.trend_following import TrendFollowingStrategy


def _row(**overrides: float) -> pd.Series:
    base = {
        "timestamp": pd.Timestamp("2023-06-01"),
        "symbol": "TEST",
        "close": 110.0,
        "sma_20": 105.0,
        "sma_50": 100.0,
        "ema_20": 106.0,
        "rsi_14": 60.0,
        "macd": 1.5,
        "macd_signal": 1.0,
        "volume": 2_000.0,
        "volume_ma_20": 1_500.0,
    }
    base.update(overrides)
    return pd.Series(base)


def test_bullish_row_yields_buy() -> None:
    decision = TrendFollowingStrategy().generate_signal(_row(), Position())
    assert decision.action is StrategySignal.BUY
    assert decision.reason
    assert 0.5 < decision.confidence <= 0.95


def test_bearish_row_yields_sell() -> None:
    # sma_20 < sma_50 and macd < signal trigger the sell branch.
    row = _row(sma_20=98.0, sma_50=100.0, macd=0.5, macd_signal=1.0)
    decision = TrendFollowingStrategy().generate_signal(row, Position(quantity=10.0))
    assert decision.action is StrategySignal.SELL
    assert decision.reason


def test_neutral_row_yields_hold() -> None:
    # Uptrend intact (no bear), but volume below average breaks the buy.
    row = _row(volume=1_000.0, volume_ma_20=1_500.0)
    decision = TrendFollowingStrategy().generate_signal(row, Position())
    assert decision.action is StrategySignal.HOLD
    assert decision.reason


def test_warmup_nan_yields_hold() -> None:
    row = _row(sma_50=float("nan"))
    decision = TrendFollowingStrategy().generate_signal(row, Position())
    assert decision.action is StrategySignal.HOLD
    assert decision.reason
