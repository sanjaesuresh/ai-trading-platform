"""Pure-logic tests for the multi-symbol portfolio backtest driver (Phase 3, M1).

DB-free. They prove: a single symbol through the portfolio driver reproduces the
single-symbol engine's golden numbers (the allocator reduces correctly); no
look-ahead (decision at bar N close fills at bar N+1 open); force-close on the
final bar; concurrent positions across symbols sharing cash; the portfolio
drawdown kill; and intersection alignment across symbols with different histories.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtesting.portfolio_backtest import run_portfolio_backtest
from app.backtesting.portfolio_core import PortfolioConfig
from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)


class _AlwaysBuy(BaseStrategy):
    name = "always_buy"

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        return StrategyDecision(action=StrategySignal.BUY, reason="always_buy")


def _frame(opens, closes=None, start="2023-01-02"):
    closes = opens if closes is None else closes
    n = len(opens)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=n, freq="D"),
            "open": opens,
            "high": [max(o, c) + 1.0 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) - 1.0 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "volume": [1_000.0] * n,
        }
    )


def test_single_symbol_matches_engine_golden_numbers() -> None:
    """One symbol through the portfolio driver = the single-symbol golden case:
    rising frame [100,102,104,106,108], 0.95 sizing, buy fills at bar-1 open=102,
    force-close at bar-4 close=108 → final equity 500 + (9500/102)*108."""
    frames = {"AAA": _frame([100.0, 102.0, 104.0, 106.0, 108.0])}
    cfg = PortfolioConfig(
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=0.95, gross_exposure_cap=1.0, max_open_positions=1,
    )
    result = run_portfolio_backtest(frames, _AlwaysBuy(), cfg)

    assert len(result.trades) == 2
    buy, sell = result.trades
    assert buy.side == "BUY"
    assert buy.price == pytest.approx(102.0)
    assert buy.quantity == pytest.approx(9_500.0 / 102.0, rel=1e-9)
    assert sell.side == "SELL"
    assert sell.price == pytest.approx(108.0)
    assert "Force-close" in sell.reason

    exp_final = 500.0 + (9_500.0 / 102.0) * 108.0
    assert result.final_equity == pytest.approx(exp_final, rel=1e-9)
    assert result.halted is False


def test_buy_fills_at_next_bar_open_not_signal_bar() -> None:
    frames = {"AAA": _frame([100.0, 105.0, 110.0, 115.0])}
    cfg = PortfolioConfig(initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
                          max_open_positions=1)
    result = run_portfolio_backtest(frames, _AlwaysBuy(), cfg)
    buy = next(t for t in result.trades if t.side == "BUY")
    # Decision is made at bar 0's close; the fill is at bar 1's open (105), and
    # the fill timestamp is bar 1 — never bar 0.
    assert buy.price == pytest.approx(105.0)
    assert buy.timestamp == frames["AAA"]["timestamp"].iloc[1]


def test_concurrent_positions_share_cash() -> None:
    """Two symbols both signalling BUY split the cash under a 0.5 per-symbol cap;
    both positions end up open."""
    frames = {
        "AAA": _frame([100.0, 100.0, 100.0]),
        "BBB": _frame([100.0, 100.0, 100.0]),
    }
    cfg = PortfolioConfig(
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=0.5, gross_exposure_cap=1.0, max_open_positions=5,
    )
    result = run_portfolio_backtest(frames, _AlwaysBuy(), cfg)
    buys = [t for t in result.trades if t.side == "BUY"]
    # One BUY per symbol, each deploying ~5_000 (50% of 10_000 equity).
    assert {t.symbol for t in buys} == {"AAA", "BBB"}
    for t in buys:
        assert t.gross_value == pytest.approx(5_000.0, rel=1e-9)


def test_portfolio_drawdown_kill_flattens_and_halts() -> None:
    """30% portfolio drawdown trips the 20% kill: flatten at next open, halt,
    no further entries (mirrors the single-symbol engine's halt numbers)."""
    frames = {"AAA": _frame([100.0, 100.0, 80.0, 80.0, 80.0],
                            [100.0, 70.0, 80.0, 80.0, 80.0])}
    cfg = PortfolioConfig(
        initial_capital=1_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=1.0, gross_exposure_cap=1.0, max_open_positions=1,
        max_drawdown_cutoff_pct=0.20,
    )
    result = run_portfolio_backtest(frames, _AlwaysBuy(), cfg)
    buys = [t for t in result.trades if t.side == "BUY"]
    sells = [t for t in result.trades if t.side == "SELL"]
    assert len(buys) == 1
    assert len(sells) == 1
    assert sells[0].price == pytest.approx(80.0)  # bar-2 open, not bar-1 close 70
    assert result.halted is True
    assert result.final_equity == pytest.approx(800.0, rel=1e-9)


def test_intersection_alignment_trades_only_common_days() -> None:
    """AAA covers days 1-5, BBB covers days 3-7; only the 3 common days are
    walked, so the equity curve has exactly 3 points on those dates."""
    frames = {
        "AAA": _frame([100.0] * 5, start="2023-01-02"),
        "BBB": _frame([100.0] * 5, start="2023-01-04"),
    }
    cfg = PortfolioConfig(initial_capital=10_000.0, fee_bps=0, slippage_bps=0)
    result = run_portfolio_backtest(frames, _AlwaysBuy(), cfg)

    common = sorted(
        set(frames["AAA"]["timestamp"]) & set(frames["BBB"]["timestamp"])
    )
    assert len(common) == 3
    assert [p.timestamp for p in result.equity_curve] == common
