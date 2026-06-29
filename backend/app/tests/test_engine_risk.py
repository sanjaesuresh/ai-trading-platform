"""Engine M4: no-look-ahead, opt-in compat, halt, vol sizing, round-trip metrics.

All tests are pure-logic and DB-free.  They extend the existing engine test
suite WITHOUT modifying it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtesting.engine import run_backtest
from app.backtesting.metrics import compute_metrics
from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)

# ---------------------------------------------------------------------------
# Helpers (local — do not import from other test modules)
# ---------------------------------------------------------------------------


class _AlwaysBuy(BaseStrategy):
    """Signal BUY every bar, regardless of position."""

    name = "always_buy"

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        return StrategyDecision(action=StrategySignal.BUY, reason="always_buy")


class _BuyOnceAtBar(BaseStrategy):
    """Signal BUY exactly once, at bar index ``signal_bar`` (0-indexed).

    This lets tests control precisely when the BUY decision is made so that
    the vol-lookback window is fully populated at decision time.
    """

    name = "buy_once"

    def __init__(self, signal_bar: int) -> None:
        self._signal_bar = signal_bar
        self._bar_count = -1

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        self._bar_count += 1
        if self._bar_count == self._signal_bar and not current_position.is_open:
            return StrategyDecision(action=StrategySignal.BUY, reason="buy_once")
        return StrategyDecision(action=StrategySignal.HOLD, reason="hold")


def _frame(opens: list[float]) -> pd.DataFrame:
    """Frame where close == open (matches the existing engine test helper)."""
    n = len(opens)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=n, freq="D"),
            "open": opens,
            "high": [o + 1.0 for o in opens],
            "low": [o - 1.0 for o in opens],
            "close": opens,
            "volume": [1_000.0] * n,
        }
    )


def _frame_oc(opens: list[float], closes: list[float]) -> pd.DataFrame:
    """Frame with explicit open and close prices."""
    n = len(opens)
    assert len(closes) == n
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=n, freq="D"),
            "open": opens,
            "high": [max(o, c) + 1.0 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) - 1.0 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "volume": [1_000.0] * n,
        }
    )


def _alt_vol_frame(n: int, daily_vol: float) -> pd.DataFrame:
    """Frame with alternating +vol / -vol close-to-close returns.

    Produces a reproducible realized volatility of approximately
    ``daily_vol * sqrt(n / (n-1))`` per the sample std formula.
    """
    closes = [100.0]
    for k in range(n - 1):
        r = daily_vol if k % 2 == 0 else -daily_vol
        closes.append(closes[-1] * (1.0 + r))
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=n, freq="D"),
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [1_000.0] * n,
        }
    )


# ---------------------------------------------------------------------------
# (a) No-look-ahead: stop triggered at bar-N close fills at bar N+1's open
# ---------------------------------------------------------------------------


def test_stop_fills_at_next_bar_open_not_same_bar_close() -> None:
    """A stop breached at bar-2 close must fill at bar-3 open, not bar-2 close.

    Frame (5 bars, fee=0, slip=0, stop_loss=15 %):
    - Bar 0 close: strategy signals BUY.
    - Bar 1 open=105: BUY fills at 105 (entry_price=105).
    - Bar 2 close=88:  88 ≤ 105*(1−0.15)=89.25 → STOP triggers (bar-2 info).
    - Bar 3 open=95:  SELL fills here (bar-3 info) — not at 88.
    """
    opens  = [100.0, 105.0, 110.0, 95.0, 100.0]
    closes = [100.0, 105.0,  88.0, 95.0, 100.0]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        stop_loss_pct=0.15,
    )

    stop_sells = [t for t in result.trades if t.reason == "stop-loss"]
    assert len(stop_sells) == 1, "expected exactly one stop-loss fill"

    sell = stop_sells[0]
    # Filled at bar 3's open (95.0), NOT at bar 2's close (88.0).
    assert sell.price == pytest.approx(95.0), (
        f"stop SELL price was {sell.price}, expected bar-3 open 95.0"
    )
    assert sell.timestamp == frame["timestamp"].iloc[3], (
        "stop SELL timestamp must be bar 3 (fill bar), not bar 2 (trigger bar)"
    )


def test_take_profit_fills_at_next_bar_open() -> None:
    """Take-profit triggered at bar-2 close fills at bar-3 open, not bar-2 close.

    Entry at bar-1 open=100.  Target = 20 % → fires at close >= 120.
    Bar-2 close = 125 ≥ 120 → TARGET queued.  Fill at bar-3 open = 130.
    """
    opens  = [100.0, 100.0, 110.0, 130.0, 100.0]
    closes = [100.0, 100.0, 125.0, 130.0, 100.0]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        take_profit_pct=0.20,
    )

    target_sells = [t for t in result.trades if t.reason == "take-profit"]
    assert len(target_sells) == 1

    sell = target_sells[0]
    assert sell.price == pytest.approx(130.0), (
        f"take-profit SELL price was {sell.price}, expected bar-3 open 130.0"
    )
    assert sell.timestamp == frame["timestamp"].iloc[3]


# ---------------------------------------------------------------------------
# (b) Opt-in backward compat: all new params None → identical to Phase 1
# ---------------------------------------------------------------------------


def test_opt_in_none_params_produces_known_outputs() -> None:
    """With all Phase 2 params None, the engine must produce specific golden outputs.

    This test is a concrete regression guard against behavioral drift from the
    Phase 1 baseline — it hard-codes expected fill prices, quantities, and final
    equity so that any inadvertent change to the no-Phase-2-params code path is
    caught immediately.

    Fixture: 5-bar rising frame [100, 102, 104, 106, 108], fee=0, slip=0,
    max_position_pct=0.95, initial=10_000.  AlwaysBuy fires at bar 0; fill at
    bar 1 (open=102); position held until force-close at bar 4 (close=108).

    Computed values (no fees, no slippage):
      budget      = 10 000 * 0.95  = 9 500
      quantity    = 9 500 / 102    ≈ 93.137 (exactly 9500/102)
      cash_left   = 10 000 − 9 500 = 500
      sell_gross  = (9500/102) * 108  = 10 058.823 529…
      final_equity = 500 + sell_gross = 10 558.823 529…
    """
    frame = _frame([100.0, 102.0, 104.0, 106.0, 108.0])

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0,
        fee_bps=0,
        slippage_bps=0,
        max_position_pct=0.95,
        target_vol=None,
        vol_lookback=20,
        stop_loss_pct=None,
        take_profit_pct=None,
        max_drawdown_cutoff_pct=None,
    )

    # Exactly 2 fills: 1 BUY + 1 force-close SELL.
    assert len(result.trades) == 2, f"expected 2 trades, got {len(result.trades)}"

    buy = result.trades[0]
    sell = result.trades[1]

    assert buy.side == "BUY"
    assert buy.price == pytest.approx(102.0)
    assert buy.quantity == pytest.approx(9_500.0 / 102.0, rel=1e-9)
    assert buy.gross_value == pytest.approx(9_500.0, rel=1e-9)

    assert sell.side == "SELL"
    assert sell.price == pytest.approx(108.0)
    assert sell.quantity == pytest.approx(9_500.0 / 102.0, rel=1e-9)
    assert sell.gross_value == pytest.approx((9_500.0 / 102.0) * 108.0, rel=1e-9)
    assert "Force-close" in sell.reason

    # Golden final equity: 500 + (9500/102)*108 = 10 558.823 529…
    _exp_final = 500.0 + (9_500.0 / 102.0) * 108.0
    assert result.final_equity == pytest.approx(_exp_final, rel=1e-9)
    assert result.halted is False
    assert result.halt_timestamp is None


# ---------------------------------------------------------------------------
# (c) Max-drawdown halt: circuit breaker flattens and suppresses new BUYs
# ---------------------------------------------------------------------------


def test_halt_after_drawdown_suppresses_new_buys() -> None:
    """After a 30 % drawdown (cutoff=20 %), engine halts and refuses further BUYs.

    Frame (5 bars, no fee/slip, initial=1000, max_pos=1.0):
    - Bar 0 close=100: BUY pending.
    - Bar 1 open=100: fill BUY (qty=10, entry=100).  close=70 → equity=700.
      Drawdown=(1000−700)/1000=30 % ≥ 20 % → halt, SELL pending.
    - Bar 2 open=80: fill SELL (cash=800).  close=80 → equity=800.
      Strategy BUY → suppressed (halted).
    - Bars 3-4: no trades.

    Total fills: exactly 1 BUY and 1 SELL.
    """
    opens  = [100.0, 100.0, 80.0, 80.0, 80.0]
    closes = [100.0,  70.0, 80.0, 80.0, 80.0]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=1_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=1.0,
        max_drawdown_cutoff_pct=0.20,
    )

    buys  = [t for t in result.trades if t.side == "BUY"]
    sells = [t for t in result.trades if t.side == "SELL"]

    assert len(buys) == 1, f"expected 1 BUY, got {len(buys)}"
    assert len(sells) == 1, f"expected 1 halt-SELL, got {len(sells)}"
    assert "halt" in sells[0].reason or "drawdown" in sells[0].reason

    # SELL fills at bar-2 open (80.0), not bar-1 close (70.0).
    assert sells[0].price == pytest.approx(80.0)
    assert sells[0].timestamp == frame["timestamp"].iloc[2]

    # BacktestResult must expose the halt and the bar that triggered it.
    # The drawdown is first detected at bar-1's close (equity=700, peak=1000),
    # so halt_timestamp must equal bar-1's timestamp.
    assert result.halted is True
    assert result.halt_timestamp == frame["timestamp"].iloc[1]


def test_halt_does_not_trip_below_cutoff() -> None:
    """Engine continues trading when drawdown stays below the cutoff."""
    # Price rises every bar → no drawdown ever → BUY + force-close only.
    opens = [100.0, 100.0, 110.0, 120.0, 130.0]
    closes = opens[:]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=1.0,
        max_drawdown_cutoff_pct=0.50,  # 50 % cutoff, never reached
    )
    buys  = [t for t in result.trades if t.side == "BUY"]
    sells = [t for t in result.trades if t.side == "SELL"]

    # One BUY (bar 1) and one force-close SELL (bar 4).
    assert len(buys) == 1
    assert len(sells) == 1
    assert "Force-close" in sells[0].reason


# ---------------------------------------------------------------------------
# (d) Vol sizing: higher realized vol → less cash deployed
# ---------------------------------------------------------------------------


def test_vol_sizing_no_lookahead_regime_change() -> None:
    """Sizing must use the TRAILING vol window (closes through bar N), not a forward window.

    Regime design:
      Bars 0..10 (11 bars): HIGH vol (5 %/day, alternating ±).
      Bars 11..24 (14 bars): LOW vol (0.5 %/day, alternating ±).

    The BUY decision fires at bar 10 (signal_bar = vol_lookback = 10).

    Correct (trailing): engine uses frame["close"].iloc[0:11] — all 10 returns
    are from the high-vol phase → fraction ≈ 0.179 → gross ≈ 18 % of initial.

    Wrong (forward): a buggy window like iloc[i : i+lookback+1] = closes[10:21]
    would include the low-vol phase → fraction capped at 0.95 → gross ≈ 95 % of
    initial.

    The assertion (gross < 40 % of initial*cap) distinguishes these cleanly:
    correct ≈ 1 790, wrong ≈ 9 500.  This test FAILS if the engine is changed to
    use a forward-looking sizing window.
    """
    vol_lookback = 10
    n_pre  = vol_lookback + 1   # 11 bars: gives exactly 10 high-vol returns
    n_post = vol_lookback + 4   # 14 bars: enough for a forward window to see
    n_total = n_pre + n_post    # 25 bars
    high_vol = 0.05             # 5 % / day
    low_vol  = 0.005            # 0.5 % / day
    cap = 0.95
    target = 0.15
    initial = 10_000.0

    # Build two-regime closes: high-vol phase then low-vol phase.
    closes: list[float] = [100.0]
    for k in range(n_pre - 1):
        closes.append(closes[-1] * (1.0 + (high_vol if k % 2 == 0 else -high_vol)))
    for k in range(n_post):
        closes.append(closes[-1] * (1.0 + (low_vol if k % 2 == 0 else -low_vol)))

    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=n_total, freq="D"),
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low":  [c * 0.999 for c in closes],
            "close": closes,
            "volume": [1_000.0] * n_total,
        }
    )

    result = run_backtest(
        frame, _BuyOnceAtBar(vol_lookback), "T",
        initial_capital=initial,
        fee_bps=0, slippage_bps=0,
        max_position_pct=cap,
        target_vol=target,
        vol_lookback=vol_lookback,
    )

    buys = [t for t in result.trades if t.side == "BUY"]
    assert len(buys) == 1, "expected exactly one BUY fill"
    buy = buys[0]

    # Trailing high-vol window (10 returns ≈ ±5 %):
    #   realized_vol_annual ≈ 0.05 * sqrt(10/9) * sqrt(252) ≈ 0.836
    #   fraction ≈ 0.15 / 0.836 ≈ 0.179  → gross ≈ 10 000 * 0.179 ≈ 1 790
    # Forward low-vol window would give fraction capped at 0.95 → gross ≈ 9 500.
    # Threshold = 40 % of (initial * cap) = 3 800 cleanly separates both cases.
    assert buy.gross_value < initial * cap * 0.40, (
        f"gross {buy.gross_value:.1f} is too large; trailing high-vol window "
        f"should yield gross ≈ {initial * target / (high_vol * (252 ** 0.5)):.0f}, "
        f"not ≈ {initial * cap:.0f} (which implies a forward-looking window)"
    )
    # Confirm vol was estimable (no 0.0 skip from the conservative fallback).
    assert buy.gross_value > 0.0


def test_vol_sizing_skips_entry_during_warmup() -> None:
    """Under vol targeting, the engine refuses to enter before a full lookback
    window exists to size against — it skips rather than max-sizing on an
    unmeasurable risk budget (same honesty rule as compute_position_fraction's
    un-estimable-vol case). With the OLD behavior this max-sized at the cap."""
    vol_lookback = 20
    # Only 5 bars total: every BUY signal fires at i < vol_lookback=20.
    frame = _frame([100.0, 100.0, 100.0, 100.0, 100.0])

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=0.60,
        target_vol=0.15,
        vol_lookback=vol_lookback,
    )

    # No entry is taken during the warmup window → no trades, capital untouched.
    assert [t for t in result.trades if t.side == "BUY"] == []
    assert result.final_equity == pytest.approx(10_000.0)


# ---------------------------------------------------------------------------
# (e) Stop/target exit produces a correct round trip in metrics
# ---------------------------------------------------------------------------


def test_stop_exit_produces_one_loss_round_trip() -> None:
    """A stop-loss exit pairs into exactly one round trip counted as a loss.

    4-bar frame (fee=0, slip=0, entry=100, stop=10 % → boundary=90):
    - Bar 0: BUY pending.
    - Bar 1 open=100: fill BUY (qty=100, gross=10000).
    - Bar 2 close=88:  88 ≤ 90 → STOP triggered.
    - Bar 3 open=90 (final bar): fill SELL at 90 (gross=9000).

    Round-trip PnL = 9000 − 10000 = −1000 → 1 loss, win_rate = 0.
    """
    opens  = [100.0, 100.0, 110.0, 90.0]
    closes = [100.0, 100.0,  88.0, 90.0]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=1.0,
        stop_loss_pct=0.10,
    )

    sells = [t for t in result.trades if t.side == "SELL"]
    assert len(sells) == 1
    assert sells[0].reason == "stop-loss"
    assert sells[0].price == pytest.approx(90.0)
    assert sells[0].timestamp == frame["timestamp"].iloc[3]

    metrics = compute_metrics(result.equity_curve, result.trades, 10_000.0)
    assert metrics.num_round_trips == 1
    assert metrics.win_rate == pytest.approx(0.0)
    assert metrics.avg_loss < 0.0
    assert metrics.profit_factor == pytest.approx(0.0)


def test_take_profit_exit_produces_one_win_round_trip() -> None:
    """A take-profit exit pairs into exactly one round trip counted as a win.

    4-bar frame (fee=0, slip=0, entry=100, target=20 % → boundary=120):
    - Bar 0: BUY pending.
    - Bar 1 open=100: fill BUY.
    - Bar 2 close=125: 125 ≥ 120 → TARGET triggered.
    - Bar 3 open=130 (final): fill SELL at 130.

    win_rate = 1.0.
    """
    opens  = [100.0, 100.0, 110.0, 130.0]
    closes = [100.0, 100.0, 125.0, 130.0]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=1.0,
        take_profit_pct=0.20,
    )

    target_sells = [t for t in result.trades if t.reason == "take-profit"]
    assert len(target_sells) == 1
    assert target_sells[0].price == pytest.approx(130.0)

    metrics = compute_metrics(result.equity_curve, result.trades, 10_000.0)
    assert metrics.num_round_trips == 1
    assert metrics.win_rate == pytest.approx(1.0)
    assert metrics.avg_win > 0.0


def test_stop_exit_with_fees_net_pnl_correct() -> None:
    """Round-trip PnL is net of both buy-side and sell-side fees."""
    # entry gross=10000, fee=50 (0.5 %).  exit gross=9000, fee=45.
    # Net PnL = (9000−45) − (10000+50) = −1095.
    opens  = [100.0, 100.0, 110.0, 90.0]
    closes = [100.0, 100.0,  88.0, 90.0]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0, fee_bps=50, slippage_bps=0,
        max_position_pct=1.0,
        stop_loss_pct=0.10,
    )

    metrics = compute_metrics(result.equity_curve, result.trades, 10_000.0)
    assert metrics.num_round_trips == 1
    assert metrics.win_rate == pytest.approx(0.0)
    # PnL must be negative and larger in magnitude than without fees.
    assert metrics.avg_loss < -1_000.0


# ---------------------------------------------------------------------------
# (f) Metrics round-trips through new exit paths (FIX 5)
# ---------------------------------------------------------------------------


def test_metrics_through_drawdown_halt_flatten() -> None:
    """compute_metrics sees exactly 1 round trip (a loss) after a drawdown halt.

    Fixture (5 bars, fee=0, slip=0, max_pct=1.0, cutoff=20 %):
      Bar 0 close=100: BUY pending.
      Bar 1 open=100: BUY fills (qty=10, gross=1000).  close=70 → equity=700.
        Drawdown = (1000−700)/1000 = 30 % ≥ 20 % → halt, SELL pending.
      Bar 2 open=80: SELL fills (gross=800, cash=800).
      Bars 3-4: halted, no position → no further trades.

    Round trip: pnl = (800 − 0) − (1000 + 0) = −200  → 1 loss.
    """
    opens  = [100.0, 100.0, 80.0, 80.0, 80.0]
    closes = [100.0,  70.0, 80.0, 80.0, 80.0]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=1_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=1.0,
        max_drawdown_cutoff_pct=0.20,
    )

    metrics = compute_metrics(result.equity_curve, result.trades, 1_000.0)

    assert metrics.num_round_trips == 1
    assert metrics.win_rate == pytest.approx(0.0)
    assert metrics.avg_loss == pytest.approx(-200.0)
    assert metrics.avg_win == pytest.approx(0.0)
    assert metrics.profit_factor == pytest.approx(0.0)


def test_metrics_through_multi_exit_round_trips() -> None:
    """compute_metrics sees 2 round trips: a stop-loss loss then a force-close win.

    Fixture (6 bars, fee=0, slip=0, max_pct=0.95, stop=10 %):
      Bar 0: BUY pending.
      Bar 1 open=100: BUY fills (budget=9500, qty=95, gross=9500, cash=500).
      Bar 2 close=88:  88 ≤ 100*(1−0.10)=90 → STOP triggered.
      Bar 3 open=90:   SELL fills (qty=95, gross=8550, cash=9050).
                       Strategy → BUY pending.
      Bar 4 open=95:   BUY fills (budget=9050*0.95=8597.5, qty=90.5,
                       gross=8597.5, cash=452.5).
      Bar 5 (final) close=110: force-close (qty=90.5, gross=9955, cash=10407.5).

    Round trip 1: pnl = 8550 − 9500 = −950  (loss, stop-loss).
    Round trip 2: pnl = 9955 − 8597.5 = +1357.5  (win, force-close).
    """
    opens  = [100.0, 100.0, 110.0,  90.0,  95.0, 110.0]
    closes = [100.0, 100.0,  88.0,  90.0,  95.0, 110.0]
    frame = _frame_oc(opens, closes)

    result = run_backtest(
        frame, _AlwaysBuy(), "T",
        initial_capital=10_000.0, fee_bps=0, slippage_bps=0,
        max_position_pct=0.95,
        stop_loss_pct=0.10,
    )

    metrics = compute_metrics(result.equity_curve, result.trades, 10_000.0)

    assert metrics.num_round_trips == 2
    assert metrics.win_rate == pytest.approx(0.5)
    # RT1 loss (stop) and RT2 win (force-close), each as the sole member of their set.
    assert metrics.avg_loss == pytest.approx(-950.0, rel=1e-9)
    assert metrics.avg_win  == pytest.approx(1357.5, rel=1e-9)
