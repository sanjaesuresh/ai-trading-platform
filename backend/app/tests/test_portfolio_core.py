"""Pure-logic tests for the shared portfolio execution core (Phase 3, M1).

All DB-free. They prove the keystone allocation/risk function and the fill
helpers behave correctly: cross-symbol allocation under the gross-exposure cap,
the max-open-positions count, the per-order notional bound, shared cash,
deterministic ranking when capacity binds, vol-sizing warm-up skip, per-symbol
stop/target exits, and the portfolio max-drawdown kill.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtesting.portfolio_core import (
    PortfolioConfig,
    PortfolioPosition,
    PortfolioState,
    SymbolContext,
    apply_buy_fill,
    apply_sell_fill,
    evaluate_portfolio,
)
from app.strategies.base_strategy import StrategySignal

_TS = pd.Timestamp("2023-01-03")


def _state(cash: float, positions=None, peak=None) -> PortfolioState:
    pos = {p.symbol: p for p in (positions or [])}
    return PortfolioState(
        cash=cash,
        positions=pos,
        peak_equity=peak if peak is not None else cash,
    )


def _buy_ctx(symbol: str, close: float, trailing=()) -> SymbolContext:
    return SymbolContext(
        symbol=symbol, close=close, decision=StrategySignal.BUY,
        reason=f"buy {symbol}", trailing_returns=tuple(trailing),
    )


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------


def test_two_buys_share_cash_under_gross_cap() -> None:
    """Both candidates get orders; the second is capped by the remaining gross
    budget once the first takes 95% of equity."""
    state = _state(100_000.0)
    cfg = PortfolioConfig(
        initial_capital=100_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=0.95, gross_exposure_cap=1.0, max_open_positions=5,
    )
    contexts = {"AAA": _buy_ctx("AAA", 100.0), "BBB": _buy_ctx("BBB", 100.0)}
    marks = {"AAA": 100.0, "BBB": 100.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    buys = {o.symbol: o.notional for o in decision.orders if o.side == "BUY"}

    # Total deployed notional cannot exceed the gross cap (= equity here).
    assert sum(buys.values()) == pytest.approx(100_000.0)
    # First-ranked (tie → alphabetical) takes the full 95% slice.
    assert buys["AAA"] == pytest.approx(95_000.0)
    assert buys["BBB"] == pytest.approx(5_000.0)


def test_max_open_positions_caps_number_of_buys() -> None:
    state = _state(100_000.0)
    cfg = PortfolioConfig(
        initial_capital=100_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=0.30, gross_exposure_cap=1.0, max_open_positions=1,
    )
    contexts = {
        "AAA": _buy_ctx("AAA", 100.0, trailing=(0.01,)),
        "BBB": _buy_ctx("BBB", 100.0, trailing=(0.10,)),  # stronger trailing move
    }
    marks = {"AAA": 100.0, "BBB": 100.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    buys = [o.symbol for o in decision.orders if o.side == "BUY"]

    # Only one slot; the stronger-ranked BBB wins it.
    assert buys == ["BBB"]


def test_ranking_tie_broken_by_symbol_name() -> None:
    state = _state(100_000.0)
    cfg = PortfolioConfig(
        initial_capital=100_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=0.50, gross_exposure_cap=1.0, max_open_positions=1,
    )
    contexts = {
        "ZZZ": _buy_ctx("ZZZ", 100.0, trailing=(0.05,)),
        "AAA": _buy_ctx("AAA", 100.0, trailing=(0.05,)),  # equal rank metric
    }
    marks = {"ZZZ": 100.0, "AAA": 100.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    buys = [o.symbol for o in decision.orders if o.side == "BUY"]
    assert buys == ["AAA"]  # alphabetical tiebreak


def test_per_order_notional_cap_limits_each_buy() -> None:
    state = _state(100_000.0)
    cfg = PortfolioConfig(
        initial_capital=100_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=0.95, gross_exposure_cap=1.0, max_open_positions=5,
        per_order_notional_cap=10_000.0,
    )
    contexts = {"AAA": _buy_ctx("AAA", 100.0), "BBB": _buy_ctx("BBB", 100.0)}
    marks = {"AAA": 100.0, "BBB": 100.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    for o in decision.orders:
        if o.side == "BUY":
            assert o.notional <= 10_000.0 + 1e-9


def test_held_symbol_is_not_rebought() -> None:
    held = PortfolioPosition(symbol="AAA", quantity=10.0, entry_price=100.0)
    state = _state(50_000.0, positions=[held])
    cfg = PortfolioConfig(initial_capital=100_000.0, fee_bps=0, slippage_bps=0)
    # AAA still signals BUY but is already open → no new order for it.
    contexts = {"AAA": _buy_ctx("AAA", 100.0)}
    marks = {"AAA": 100.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    assert [o for o in decision.orders if o.symbol == "AAA"] == []


def test_vol_targeting_skips_when_window_missing() -> None:
    """With vol targeting on and no trailing window (warm-up), refuse to size."""
    state = _state(100_000.0)
    cfg = PortfolioConfig(
        initial_capital=100_000.0, fee_bps=0, slippage_bps=0,
        target_vol=0.15, vol_lookback=20, max_position_pct=0.95,
    )
    contexts = {"AAA": _buy_ctx("AAA", 100.0, trailing=())}  # empty window
    marks = {"AAA": 100.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    assert [o for o in decision.orders if o.side == "BUY"] == []


# ---------------------------------------------------------------------------
# Exits
# ---------------------------------------------------------------------------


def test_stop_loss_exit_emitted_for_held_position() -> None:
    held = PortfolioPosition(symbol="AAA", quantity=10.0, entry_price=100.0)
    state = _state(0.0, positions=[held])
    cfg = PortfolioConfig(initial_capital=1_000.0, stop_loss_pct=0.10)
    # close 88 <= 100*(1-0.10)=90 → stop triggers.
    contexts = {
        "AAA": SymbolContext("AAA", 88.0, StrategySignal.HOLD, "hold", ())
    }
    marks = {"AAA": 88.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    sells = [o for o in decision.orders if o.side == "SELL"]
    assert len(sells) == 1
    assert sells[0].reason == "stop-loss"


def test_strategy_sell_exits_held_position() -> None:
    held = PortfolioPosition(symbol="AAA", quantity=10.0, entry_price=100.0)
    state = _state(0.0, positions=[held])
    cfg = PortfolioConfig(initial_capital=1_000.0)
    contexts = {
        "AAA": SymbolContext("AAA", 100.0, StrategySignal.SELL, "trend gone", ())
    }
    marks = {"AAA": 100.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    sells = [o for o in decision.orders if o.side == "SELL"]
    assert len(sells) == 1
    assert sells[0].reason == "trend gone"


# ---------------------------------------------------------------------------
# Portfolio drawdown kill
# ---------------------------------------------------------------------------


def test_drawdown_kill_flattens_and_blocks_new_buys() -> None:
    """Equity 700 vs peak 1000 = 30% drawdown > 20% cutoff → flatten all, no
    new entries, halt flagged."""
    held = PortfolioPosition(symbol="AAA", quantity=10.0, entry_price=100.0)
    state = _state(0.0, positions=[held], peak=1_000.0)
    cfg = PortfolioConfig(
        initial_capital=1_000.0, fee_bps=0, slippage_bps=0,
        max_drawdown_cutoff_pct=0.20,
    )
    # AAA marked at 70 → equity 700. BBB also signals BUY but must be suppressed.
    contexts = {
        "AAA": SymbolContext("AAA", 70.0, StrategySignal.HOLD, "hold", ()),
        "BBB": _buy_ctx("BBB", 50.0),
    }
    marks = {"AAA": 70.0, "BBB": 50.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    assert decision.halt_triggered is True
    sells = [o for o in decision.orders if o.side == "SELL"]
    buys = [o for o in decision.orders if o.side == "BUY"]
    assert [s.symbol for s in sells] == ["AAA"]
    assert sells[0].reason == "portfolio max-drawdown halt"
    assert buys == []


def test_already_halted_state_suppresses_buys() -> None:
    state = _state(100_000.0)
    state.halted = True
    cfg = PortfolioConfig(initial_capital=100_000.0, max_drawdown_cutoff_pct=0.20)
    contexts = {"AAA": _buy_ctx("AAA", 100.0)}
    marks = {"AAA": 100.0}

    decision = evaluate_portfolio(state, contexts, marks, cfg)
    assert decision.halt_triggered is False  # not *newly* tripped
    assert [o for o in decision.orders if o.side == "BUY"] == []


# ---------------------------------------------------------------------------
# Fill helpers
# ---------------------------------------------------------------------------


def test_apply_buy_fill_deploys_budget_and_decrements_cash() -> None:
    state = _state(100_000.0)
    cfg = PortfolioConfig(initial_capital=100_000.0, fee_bps=0, slippage_bps=0)
    rec = apply_buy_fill(state, "AAA", _TS, 100.0, 9_500.0, {"AAA": 100.0}, cfg, "buy")
    assert rec is not None
    assert rec.side == "BUY"
    assert rec.quantity == pytest.approx(95.0)
    assert state.cash == pytest.approx(90_500.0)
    assert state.positions["AAA"].quantity == pytest.approx(95.0)
    assert rec.reason == "buy"


def test_apply_buy_fill_caps_at_available_cash() -> None:
    state = _state(1_000.0)
    cfg = PortfolioConfig(initial_capital=1_000.0, fee_bps=0, slippage_bps=0)
    # Ask for 5_000 notional but only 1_000 cash available.
    rec = apply_buy_fill(state, "AAA", _TS, 100.0, 5_000.0, {"AAA": 100.0}, cfg)
    assert rec is not None
    assert rec.gross_value == pytest.approx(1_000.0)
    assert state.cash == pytest.approx(0.0)


def test_apply_sell_fill_closes_full_position() -> None:
    held = PortfolioPosition(symbol="AAA", quantity=10.0, entry_price=100.0)
    state = _state(0.0, positions=[held])
    cfg = PortfolioConfig(initial_capital=1_000.0, fee_bps=0, slippage_bps=0)
    rec = apply_sell_fill(state, "AAA", _TS, 120.0, {"AAA": 120.0}, cfg, "exit")
    assert rec is not None
    assert rec.quantity == pytest.approx(10.0)
    assert state.cash == pytest.approx(1_200.0)
    assert state.positions["AAA"].is_open is False


def test_apply_sell_fill_on_flat_returns_none() -> None:
    state = _state(1_000.0)
    cfg = PortfolioConfig(initial_capital=1_000.0)
    assert apply_sell_fill(state, "AAA", _TS, 100.0, {"AAA": 100.0}, cfg, "x") is None
