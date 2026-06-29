"""Metrics: edge cases, known drawdown, win rate over round trips, zero vol."""

from __future__ import annotations

import math

import pandas as pd

from app.backtesting.engine import EquityPoint, TradeRecord
from app.backtesting.metrics import compute_metrics


def _curve(equities: list[float]) -> list[EquityPoint]:
    ts = pd.date_range("2023-01-02", periods=len(equities), freq="D")
    return [EquityPoint(timestamp=t, equity=e, cash=e, position_value=0.0)
            for t, e in zip(ts, equities, strict=True)]


def _trade(side: str, day: int, gross: float, fee: float = 0.0) -> TradeRecord:
    return TradeRecord(
        symbol="T", side=side, timestamp=pd.Timestamp("2023-01-01") + pd.Timedelta(days=day),
        price=0.0, quantity=0.0, gross_value=gross, fee=fee, slippage=0.0,
        cash_after=0.0, position_after=0.0, equity_after=0.0, reason="",
    )


def test_no_trades_is_safe() -> None:
    m = compute_metrics(_curve([100.0] * 10), [], initial_capital=100.0)
    assert m.num_round_trips == 0
    assert m.win_rate == 0.0
    assert m.profit_factor == 0.0
    assert m.max_drawdown_pct == 0.0
    assert m.sharpe_ratio == 0.0


def test_known_max_drawdown() -> None:
    # Peak 120 then trough 90 -> 25% drawdown.
    m = compute_metrics(_curve([100.0, 120.0, 90.0, 130.0]), [], initial_capital=100.0)
    assert abs(m.max_drawdown_pct - 25.0) < 1e-9


def test_win_rate_over_round_trips() -> None:
    # One winning round trip (1000 -> 1100) and one losing (1000 -> 900).
    trades = [
        _trade("BUY", 0, 1_000.0),
        _trade("SELL", 2, 1_100.0),
        _trade("BUY", 3, 1_000.0),
        _trade("SELL", 5, 900.0),
    ]
    m = compute_metrics(_curve([100.0, 110.0, 105.0, 108.0]), trades, initial_capital=100.0)
    assert m.num_round_trips == 2
    assert abs(m.win_rate - 0.5) < 1e-9
    assert abs(m.profit_factor - 1.0) < 1e-9  # +100 profit / 100 loss
    assert m.avg_win > 0 and m.avg_loss < 0


def test_zero_volatility_no_error() -> None:
    m = compute_metrics(_curve([100.0] * 20), [], initial_capital=100.0)
    assert m.sharpe_ratio == 0.0
    assert m.sortino_ratio == 0.0


def test_only_winners_profit_factor_finite_or_inf() -> None:
    trades = [_trade("BUY", 0, 1_000.0), _trade("SELL", 2, 1_200.0)]
    m = compute_metrics(_curve([100.0, 110.0, 120.0]), trades, initial_capital=100.0)
    assert m.win_rate == 1.0
    assert m.profit_factor == float("inf")


def test_only_losers_profit_factor_zero() -> None:
    trades = [_trade("BUY", 0, 1_000.0), _trade("SELL", 2, 900.0)]
    m = compute_metrics(_curve([100.0, 95.0, 90.0]), trades, initial_capital=100.0)
    assert m.win_rate == 0.0
    assert m.profit_factor == 0.0
    assert m.avg_loss < 0.0


def test_sortino_handles_uniform_magnitude_losses() -> None:
    # Returns +1%, -2%, +1%, -2%, +1%: the two losses are identical in size.
    # Downside deviation (RMS about 0) must stay positive — the de-meaned std of
    # losers would be 0 here and wrongly zero out Sortino. Mean return is
    # negative, so Sortino must be a finite negative number, not 0.
    equities = [100.0]
    for r in (0.01, -0.02, 0.01, -0.02, 0.01):
        equities.append(equities[-1] * (1.0 + r))
    m = compute_metrics(_curve(equities), [], initial_capital=100.0)
    assert math.isfinite(m.sortino_ratio)
    assert m.sortino_ratio < 0.0


def test_sortino_zero_when_no_downside() -> None:
    # Monotonically rising equity has no negative returns -> Sortino defined as 0.
    m = compute_metrics(_curve([100.0, 101.0, 102.0, 103.0]), [], initial_capital=100.0)
    assert m.sortino_ratio == 0.0
