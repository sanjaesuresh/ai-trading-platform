"""Trend-following parameterization + characterization.

The retrofit adds tunable RSI bands as constructor params. These tests pin that
the defaults reproduce the Phase 1 baseline exactly (action *and* reason), and
that custom params actually change the decision. Pure-logic, DB-free.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base_strategy import Position, StrategySignal
from app.strategies.trend_following import TrendFollowingStrategy


def _row(**overrides: float) -> pd.Series:
    base = {
        "timestamp": pd.Timestamp("2023-06-01"),
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


def test_default_params_match_baseline_constants() -> None:
    strat = TrendFollowingStrategy()
    assert strat.rsi_buy_low == 45.0
    assert strat.rsi_buy_high == 75.0
    assert strat.rsi_sell_high == 80.0


def test_default_buy_reason_is_unchanged() -> None:
    """Characterization: the BUY reason string is exactly the Phase 1 text."""
    decision = TrendFollowingStrategy().generate_signal(_row(), Position())
    assert decision.action is StrategySignal.BUY
    assert decision.reason == (
        "Buy: SMA-20 > SMA-50, close > SMA-20, RSI in [45,75], MACD > signal, volume > avg"
    )


def test_default_sell_reason_is_unchanged() -> None:
    row = _row(sma_20=98.0, sma_50=100.0, macd=0.5, macd_signal=1.0)
    decision = TrendFollowingStrategy().generate_signal(row, Position(quantity=10.0))
    assert decision.action is StrategySignal.SELL
    assert decision.reason == "Sell: SMA-20 < SMA-50, MACD < signal"


def test_explicit_defaults_equal_implicit() -> None:
    row = _row()
    implicit = TrendFollowingStrategy().generate_signal(row, Position())
    explicit = TrendFollowingStrategy(45.0, 75.0, 80.0).generate_signal(row, Position())
    assert implicit.action == explicit.action
    assert implicit.reason == explicit.reason


def test_custom_rsi_floor_changes_decision() -> None:
    # rsi=60 buys with the default 45 floor; raising the floor to 65 blocks it.
    row = _row(rsi_14=60.0)
    assert TrendFollowingStrategy().generate_signal(row, Position()).action is (
        StrategySignal.BUY
    )
    assert TrendFollowingStrategy(rsi_buy_low=65.0).generate_signal(row, Position()).action is (
        StrategySignal.HOLD
    )
