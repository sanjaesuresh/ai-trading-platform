"""Pure-logic tests for portfolio metrics (Phase 3, M1).

The critical new behaviour is round-trip pairing across *concurrent* positions:
the global fill stream is no longer a single alternating BUY/SELL sequence, so
pairing must be per symbol. These tests prove that, plus the edge cases.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtesting.engine import EquityPoint, TradeRecord
from app.backtesting.portfolio_metrics import compute_portfolio_metrics

_T0 = pd.Timestamp("2023-01-02")
_T1 = pd.Timestamp("2023-01-03")


def _rec(symbol, side, gross, ts, fee=0.0) -> TradeRecord:
    return TradeRecord(
        symbol=symbol, side=side, timestamp=ts, price=gross / 10.0, quantity=10.0,
        gross_value=gross, fee=fee, slippage=0.0, cash_after=0.0,
        position_after=(10.0 if side == "BUY" else 0.0), equity_after=0.0, reason="",
    )


def _curve(equities) -> list[EquityPoint]:
    return [
        EquityPoint(timestamp=_T0 + pd.Timedelta(days=i), equity=e, cash=e,
                    position_value=0.0)
        for i, e in enumerate(equities)
    ]


def test_round_trips_paired_per_symbol_not_globally() -> None:
    """Interleaved fills (BUY AAA, BUY BBB, SELL AAA, SELL BBB) must pair into one
    round trip per symbol — global alternation would mis-pair these."""
    trades = [
        _rec("AAA", "BUY", 1_000.0, _T0),
        _rec("BBB", "BUY", 1_000.0, _T0),
        _rec("AAA", "SELL", 1_200.0, _T1),  # +200 win
        _rec("BBB", "SELL", 800.0, _T1),    # -200 loss
    ]
    m = compute_portfolio_metrics(_curve([2_000.0, 2_000.0]), trades, 2_000.0)
    assert m.num_round_trips == 2
    assert m.num_fills == 4
    assert m.win_rate == pytest.approx(0.5)
    assert m.avg_win == pytest.approx(200.0)
    assert m.avg_loss == pytest.approx(-200.0)
    assert m.profit_factor == pytest.approx(1.0)


def test_no_trades_is_edge_case_safe() -> None:
    m = compute_portfolio_metrics(_curve([1_000.0, 1_000.0]), [], 1_000.0)
    assert m.num_round_trips == 0
    assert m.win_rate == 0.0
    assert m.profit_factor == 0.0
    assert m.sharpe_ratio == 0.0


def test_only_winners_gives_infinite_profit_factor() -> None:
    trades = [
        _rec("AAA", "BUY", 1_000.0, _T0),
        _rec("AAA", "SELL", 1_100.0, _T1),
    ]
    m = compute_portfolio_metrics(_curve([1_000.0, 1_100.0]), trades, 1_000.0)
    assert m.num_round_trips == 1
    assert m.win_rate == pytest.approx(1.0)
    assert m.profit_factor == float("inf")


def test_equity_stats_use_portfolio_curve() -> None:
    """Drawdown and return come from the portfolio equity curve regardless of
    position count."""
    m = compute_portfolio_metrics(
        _curve([1_000.0, 1_200.0, 900.0]), [], 1_000.0
    )
    assert m.total_return_pct == pytest.approx(-10.0)  # 900 vs 1000
    # Peak 1200 → trough 900 = 25% drawdown.
    assert m.max_drawdown_pct == pytest.approx(25.0)
