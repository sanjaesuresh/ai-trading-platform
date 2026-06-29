"""Mean-reversion signal logic on crafted rows. Pure-logic, DB-free.

Entries fire below the lower band, exits on reversion to the exit band, warm-up
NaN abstains. The strategy reads only the passed row's close + indicators, so it
cannot see the future; next-bar-open execution is the engine's job (covered in
test_mean_reversion_engine).
"""

from __future__ import annotations

import pandas as pd

from app.strategies.base_strategy import Position, StrategySignal
from app.strategies.mean_reversion import MeanReversionStrategy


def _row(close: float, sma_20: float = 100.0, std_20: float = 5.0) -> pd.Series:
    return pd.Series(
        {
            "timestamp": pd.Timestamp("2023-06-01"),
            "close": close,
            "sma_20": sma_20,
            "std_20": std_20,
        }
    )


def test_below_lower_band_yields_buy() -> None:
    # lower band = 100 - 2*5 = 90; close 85 is below it.
    decision = MeanReversionStrategy().generate_signal(_row(85.0), Position())
    assert decision.action is StrategySignal.BUY
    assert decision.reason


def test_at_mean_yields_sell() -> None:
    # exit band with default exit_std=0 is the mean (100); close 101 >= 100.
    decision = MeanReversionStrategy().generate_signal(_row(101.0), Position(quantity=10.0))
    assert decision.action is StrategySignal.SELL


def test_between_bands_yields_hold() -> None:
    # 90 (lower) <= 95 < 100 (exit) -> hold.
    decision = MeanReversionStrategy().generate_signal(_row(95.0), Position(quantity=10.0))
    assert decision.action is StrategySignal.HOLD


def test_warmup_nan_yields_hold() -> None:
    decision = MeanReversionStrategy().generate_signal(_row(85.0, std_20=float("nan")), Position())
    assert decision.action is StrategySignal.HOLD


def test_entry_std_widens_threshold() -> None:
    # With entry_std=1, lower band = 95; close 94 buys. With default 2 (lower 90)
    # the same close would only hold.
    row = _row(94.0)
    assert MeanReversionStrategy(entry_std=1.0).generate_signal(row, Position()).action is (
        StrategySignal.BUY
    )
    assert MeanReversionStrategy().generate_signal(row, Position()).action is StrategySignal.HOLD


def test_exit_std_lowers_exit_band() -> None:
    # exit_std=1 -> exit band = 95; close 96 sells. Default exit_std=0 (band 100)
    # would hold at 96.
    row = _row(96.0)
    assert MeanReversionStrategy(entry_std=2.0, exit_std=1.0).generate_signal(
        row, Position(quantity=10.0)
    ).action is StrategySignal.SELL
    assert MeanReversionStrategy().generate_signal(
        row, Position(quantity=10.0)
    ).action is StrategySignal.HOLD
