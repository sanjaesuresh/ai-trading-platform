"""Pure-logic tests for the paper-trading service (Phase 3, M3).

DB-free: the decision/submit/reconcile logic runs against the deterministic
FakeBroker and in-memory featured frames. A stub strategy (injected via
monkeypatch) gives deterministic BUY/SELL signals so the order translation,
idempotency, slippage attribution, reconciliation, and the drawdown kill are
all verified without a database.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.backtesting.portfolio_core import PortfolioConfig
from app.brokers.base import OrderRequest, OrderSide, TimeInForce
from app.brokers.fake import FakeBroker
from app.services import paper_trading_service as svc
from app.services.paper_trading_service import (
    DeploymentSpec,
    _should_warn_ml_min_hold,
    attribute_fills,
    build_portfolio_config,
    deterministic_client_id,
    plan_cycle,
    portfolio_snapshot_values,
    reconcile,
    state_from_broker,
    submit_plan,
)
from app.strategies.base_strategy import (
    BaseStrategy,
    Position,
    StrategyDecision,
    StrategySignal,
)
from app.strategies.ml_classifier import MLClassifierStrategy

_DAY = date(2023, 1, 10)


class _Stub(BaseStrategy):
    name = "stub"

    def __init__(self, action: StrategySignal) -> None:
        self._action = action

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        return StrategyDecision(action=self._action, reason="stub")


@pytest.fixture
def stub_buy(monkeypatch):
    monkeypatch.setattr(svc, "resolve_strategy", lambda name, params: _Stub(StrategySignal.BUY))


@pytest.fixture
def stub_sell(monkeypatch):
    monkeypatch.setattr(svc, "resolve_strategy", lambda name, params: _Stub(StrategySignal.SELL))


def _frame(opens: list[float], closes: list[float], start="2023-01-03") -> pd.DataFrame:
    n = len(opens)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=n, freq="D"),
            "open": opens,
            "high": [max(o, c) + 1 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) - 1 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


def _spec(symbols, **cfg) -> DeploymentSpec:
    base = {
        "initial_capital": 100_000.0, "fee_bps": 0, "slippage_bps": 0,
        "max_position_pct": 0.5, "gross_exposure_cap": 1.0, "max_open_positions": 5,
    }
    base.update(cfg)
    return DeploymentSpec(
        deployment_id=1, strategy_name="trend_following", params={},
        symbols=list(symbols), config=PortfolioConfig(**base),
    )


# Frames cover 2023-01-03..2023-01-10 (8 bars); the decision bar is 2023-01-09
# (the latest bar strictly before the 2023-01-10 trading day).
def _flat_frames(symbols):
    opens = [100.0] * 7 + [100.5]  # last bar (trading_day) opens at 100.5
    closes = [100.0] * 8
    return {s: _frame(opens, closes) for s in symbols}


# --- Config / state ---------------------------------------------------------


def test_build_portfolio_config_filters_known_fields() -> None:
    cfg = build_portfolio_config(
        50_000.0, {"fee_bps": 7.0, "max_open_positions": 3, "bogus": 1}
    )
    assert cfg.initial_capital == 50_000.0
    assert cfg.fee_bps == 7.0
    assert cfg.max_open_positions == 3


def test_state_from_broker_reflects_positions_and_cash() -> None:
    broker = FakeBroker(cash=100_000.0)
    o = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10))
    broker.fill(o.id, price=100.0)
    state = state_from_broker(broker, ["AAA", "BBB"])
    assert state.cash == pytest.approx(99_000.0)
    assert state.positions["AAA"].quantity == pytest.approx(10.0)
    assert state.positions["BBB"].is_open is False


def test_deterministic_client_id_is_stable() -> None:
    cid = deterministic_client_id(1, _DAY, "AAA", "BUY")
    assert cid == "dep1-2023-01-10-AAA-BUY"


# --- plan_cycle -------------------------------------------------------------


def test_plan_cycle_translates_buys_to_whole_shares(stub_buy) -> None:
    broker = FakeBroker(cash=100_000.0)
    spec = _spec(["AAA", "BBB"])
    plan = plan_cycle(broker, spec, _flat_frames(["AAA", "BBB"]), _DAY, peak_equity=100_000.0)

    buys = {o.symbol: o for o in plan.orders}
    assert set(buys) == {"AAA", "BBB"}
    # 0.5 * 100k equity / 100 ref = 500 whole shares each.
    for o in plan.orders:
        assert o.side == "BUY"
        assert o.quantity == pytest.approx(500.0)
        assert o.request.time_in_force == TimeInForce.OPG
        assert o.request.client_order_id == f"dep1-2023-01-10-{o.symbol}-BUY"


def test_plan_cycle_skips_symbol_without_prior_bar(stub_buy) -> None:
    # AAA's frame starts ON the trading day → no prior decision bar → no order.
    frames = {"AAA": _frame([100.0], [100.0], start="2023-01-10")}
    plan = plan_cycle(FakeBroker(), _spec(["AAA"]), frames, _DAY, peak_equity=100_000.0)
    assert plan.orders == []


def test_plan_cycle_sell_closes_full_position(stub_sell) -> None:
    broker = FakeBroker(cash=100_000.0)
    o = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10))
    broker.fill(o.id, price=100.0)
    plan = plan_cycle(broker, _spec(["AAA"]), _flat_frames(["AAA"]), _DAY, peak_equity=100_000.0)
    assert len(plan.orders) == 1
    sell = plan.orders[0]
    assert sell.side == "SELL"
    assert sell.quantity == pytest.approx(10.0)
    assert sell.request.side == OrderSide.SELL


def test_plan_cycle_drawdown_kill_halts_and_flattens(stub_buy) -> None:
    broker = FakeBroker(cash=100_000.0)
    o = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10))
    broker.fill(o.id, price=100.0)
    spec = _spec(["AAA"], max_drawdown_cutoff_pct=0.20)
    # Peak 200k vs current ~100k equity = 50% drawdown > 20% → kill.
    plan = plan_cycle(broker, spec, _flat_frames(["AAA"]), _DAY, peak_equity=200_000.0)
    assert plan.halt_triggered is True
    assert [o.side for o in plan.orders] == ["SELL"]  # flatten, no new buys


# --- submit / fills / reconcile --------------------------------------------


def test_submit_plan_is_idempotent(stub_buy) -> None:
    broker = FakeBroker(cash=100_000.0)
    plan = plan_cycle(broker, _spec(["AAA"]), _flat_frames(["AAA"]), _DAY, peak_equity=100_000.0)
    first = submit_plan(broker, plan)
    second = submit_plan(broker, plan)
    # Same client id → same broker order, no duplicate.
    assert list(first) == list(second)
    assert first[next(iter(first))].id == second[next(iter(second))].id
    assert len(broker.list_open_orders()) == 1


def test_attribute_fills_computes_slippage_vs_modeled_open(stub_buy) -> None:
    broker = FakeBroker(cash=100_000.0)
    frames = _flat_frames(["AAA"])  # trading-day bar opens at 100.5
    plan = plan_cycle(broker, _spec(["AAA"]), frames, _DAY, peak_equity=100_000.0)
    submitted = submit_plan(broker, plan)
    order = submitted[plan.orders[0].client_order_id]
    broker.fill(order.id, price=101.0)  # realized fill above the modeled open

    fills = attribute_fills(broker, plan.orders, frames, _DAY)
    assert len(fills) == 1
    f = fills[0]
    assert f.modeled_reference_price == pytest.approx(100.5)
    # BUY filled above the modeled open → positive (adverse) cost.
    assert f.slippage_delta == pytest.approx(0.5)  # 101.0 - 100.5


def test_reconcile_flags_reject_and_unexpected_position(stub_buy) -> None:
    # Broker rejects AAA orders and already holds an out-of-basket symbol.
    broker = FakeBroker(cash=100_000.0, reject_symbols=["AAA"])
    surprise = broker.submit_order(OrderRequest("ZZZ", OrderSide.BUY, 5))
    broker.fill(surprise.id, price=10.0)

    spec = _spec(["AAA"])
    plan = plan_cycle(broker, spec, _flat_frames(["AAA"]), _DAY, peak_equity=100_000.0)
    submit_plan(broker, plan)
    records = reconcile(broker, spec.symbols, plan.orders)
    kinds = {r.kind for r in records}
    assert "reject" in kinds
    assert "unexpected_position" in kinds


def test_sell_slippage_is_cost_signed(stub_sell) -> None:
    """A SELL filled below the modeled open is an adverse (positive) cost."""
    broker = FakeBroker(cash=100_000.0)
    o = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10))
    broker.fill(o.id, price=100.0)
    frames = _flat_frames(["AAA"])  # trading-day open = 100.5
    plan = plan_cycle(broker, _spec(["AAA"]), frames, _DAY, peak_equity=100_000.0)
    submitted = submit_plan(broker, plan)
    sell_order = submitted[plan.orders[0].client_order_id]
    broker.fill(sell_order.id, price=100.0)  # sold below the 100.5 modeled open

    fills = attribute_fills(broker, plan.orders, frames, _DAY)
    assert fills[0].side == "SELL"
    # modeled - fill = 100.5 - 100.0 = 0.5 adverse.
    assert fills[0].slippage_delta == pytest.approx(0.5)


def test_live_plan_relays_the_core_allocation(stub_buy) -> None:
    """Equivalence guard (§14): the live runner's planned BUY notionals equal the
    shared portfolio core's target orders for the same state and bars — the live
    allocator cannot drift from what the backtest would do."""
    from app.backtesting.portfolio_core import build_symbol_context, evaluate_portfolio
    from app.services.paper_trading_service import _decision_index

    broker = FakeBroker(cash=100_000.0)
    spec = _spec(["AAA", "BBB"])
    frames = _flat_frames(["AAA", "BBB"])
    plan = plan_cycle(broker, spec, frames, _DAY, peak_equity=100_000.0)

    # Reconstruct the core decision through the same shared seams.
    state = state_from_broker(broker, ["AAA", "BBB"])
    state.peak_equity = 100_000.0
    contexts, marks = {}, {}
    for sym in ["AAA", "BBB"]:
        idx = _decision_index(frames[sym], _DAY)
        closes = frames[sym]["close"].to_numpy(dtype=float).tolist()
        dec = _Stub(StrategySignal.BUY).generate_signal(frames[sym].iloc[idx], Position())
        contexts[sym] = build_symbol_context(sym, dec, closes, idx, spec.config)
        marks[sym] = closes[idx]
    core = evaluate_portfolio(state, contexts, marks, spec.config)

    core_buys = {o.symbol: o.notional for o in core.orders if o.side == "BUY"}
    plan_buys = {o.symbol: o.notional for o in plan.orders}
    assert plan_buys.keys() == core_buys.keys()
    for sym in plan_buys:
        assert plan_buys[sym] == pytest.approx(core_buys[sym])


def test_portfolio_snapshot_values_from_broker_truth() -> None:
    broker = FakeBroker(cash=100_000.0)
    o = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10))
    broker.fill(o.id, price=100.0)
    values = portfolio_snapshot_values(broker, peak_equity=120_000.0)
    assert values["equity"] == pytest.approx(100_000.0)  # 99k cash + 1k position
    assert values["position_value"] == pytest.approx(1_000.0)
    assert values["num_positions"] == 1
    # Drawdown vs the 120k peak: (120k-100k)/120k = 16.67%.
    assert values["drawdown_pct"] == pytest.approx(100 * 20_000 / 120_000)


# --- ML min-hold gap warning (Finding #1) -----------------------------------


class _FakeMLStrategy(MLClassifierStrategy):
    """Minimal MLClassifierStrategy stub that bypasses model loading.

    Used only to test the isinstance-based ``_should_warn_ml_min_hold`` check
    and the warning path in ``plan_cycle`` without requiring a real trained model
    on disk.  ``generate_signal`` is overridden to avoid calling ``self._model``.
    """

    def __init__(self, min_hold: int = 3) -> None:  # no super().__init__()
        self.min_hold = min_hold
        self._bars_held = 0
        self.model_id = "(test)"
        self.enter_threshold = 0.6
        self.exit_threshold = 0.4
        self._cols: list[str] = []
        self._model = None  # type: ignore[assignment]

    def generate_signal(self, row: pd.Series, current_position: Position) -> StrategyDecision:
        return StrategyDecision(action=StrategySignal.BUY, reason="fake_ml")


def test_should_warn_ml_min_hold_fires_for_ml_gt1_not_for_rule() -> None:
    """Unit-test the helper that gates the warning: True for ML(min_hold>1), False otherwise."""
    assert _should_warn_ml_min_hold(_FakeMLStrategy(min_hold=3)) is True
    assert _should_warn_ml_min_hold(_FakeMLStrategy(min_hold=5)) is True
    # min_hold=0 or 1 does not trip the gate.
    assert _should_warn_ml_min_hold(_FakeMLStrategy(min_hold=1)) is False
    assert _should_warn_ml_min_hold(_FakeMLStrategy(min_hold=0)) is False
    # A plain rule strategy (not an ML classifier) never triggers the warning.
    assert _should_warn_ml_min_hold(_Stub(StrategySignal.BUY)) is False


def test_plan_cycle_warns_for_ml_min_hold_not_for_rule(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``plan_cycle`` emits a WARNING for ML(min_hold>1) and not for a rule strategy."""
    import logging

    broker = FakeBroker(cash=100_000.0)
    frames = _flat_frames(["AAA"])
    spec = _spec(["AAA"])

    # ML path: warning must appear.
    monkeypatch.setattr(
        svc, "resolve_strategy",
        lambda name, params: _FakeMLStrategy(min_hold=3),
    )
    with caplog.at_level(logging.WARNING, logger="app.services.paper_trading_service"):
        plan_cycle(broker, spec, frames, _DAY, peak_equity=100_000.0)

    assert any(
        "min_hold" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    ), "Expected a WARNING about ML min-hold gap but none was emitted."

    # Rule path: no min-hold warning.
    caplog.clear()
    monkeypatch.setattr(
        svc, "resolve_strategy",
        lambda name, params: _Stub(StrategySignal.BUY),
    )
    with caplog.at_level(logging.WARNING, logger="app.services.paper_trading_service"):
        plan_cycle(broker, spec, frames, _DAY, peak_equity=100_000.0)

    assert not any(
        "min_hold" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    ), "Unexpected ML min-hold WARNING emitted for a plain rule strategy."
