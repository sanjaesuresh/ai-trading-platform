"""Tests for the deterministic in-memory FakeBroker (Phase 3, M2).

No network, no keys. Exercise the full BrokerPort surface plus the test controls:
accept/reject, idempotency, full and partial fills, cash/position accounting,
cancel, and fills-since filtering.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.brokers.base import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from app.brokers.fake import FakeBroker


def _buy(symbol: str, qty: float, client_id: str | None = None) -> OrderRequest:
    return OrderRequest(
        symbol=symbol, side=OrderSide.BUY, quantity=qty,
        type=OrderType.MARKET, time_in_force=TimeInForce.OPG,
        client_order_id=client_id,
    )


def test_submit_accepts_and_is_readable() -> None:
    broker = FakeBroker(cash=100_000.0)
    order = broker.submit_order(_buy("AAA", 10))
    assert order.status == OrderStatus.ACCEPTED
    assert order.time_in_force == TimeInForce.OPG
    assert broker.get_order(order.id).id == order.id
    assert broker.list_open_orders() == [order]


def test_client_order_id_is_idempotent() -> None:
    broker = FakeBroker()
    a = broker.submit_order(_buy("AAA", 10, client_id="dep1-AAA-2023-01-03"))
    b = broker.submit_order(_buy("AAA", 10, client_id="dep1-AAA-2023-01-03"))
    assert a.id == b.id  # second submit returns the existing order, no duplicate
    assert broker.get_order_by_client_id("dep1-AAA-2023-01-03").id == a.id


def test_full_fill_updates_cash_and_position() -> None:
    broker = FakeBroker(cash=100_000.0)
    order = broker.submit_order(_buy("AAA", 10))
    fill = broker.fill(order.id, price=100.0)
    assert fill.quantity == pytest.approx(10.0)

    filled = broker.get_order(order.id)
    assert filled.status == OrderStatus.FILLED
    assert filled.filled_avg_price == pytest.approx(100.0)

    acct = broker.get_account()
    assert acct.cash == pytest.approx(99_000.0)  # 100k - 10*100
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAA"
    assert positions[0].quantity == pytest.approx(10.0)
    assert acct.equity == pytest.approx(100_000.0)  # cash + position value


def test_partial_fill_then_complete() -> None:
    broker = FakeBroker()
    order = broker.submit_order(_buy("AAA", 10))
    broker.partially_fill(order.id, quantity=4, price=100.0)
    mid = broker.get_order(order.id)
    assert mid.status == OrderStatus.PARTIALLY_FILLED
    assert mid.filled_quantity == pytest.approx(4.0)
    assert mid in broker.list_open_orders()

    broker.partially_fill(order.id, quantity=6, price=110.0)
    done = broker.get_order(order.id)
    assert done.status == OrderStatus.FILLED
    assert done.filled_quantity == pytest.approx(10.0)
    # VWAP across partials: (4*100 + 6*110)/10 = 106.
    assert done.filled_avg_price == pytest.approx(106.0)
    assert done not in broker.list_open_orders()


def test_rejected_symbol_is_not_filled() -> None:
    broker = FakeBroker(reject_symbols=["BAD"])
    order = broker.submit_order(_buy("BAD", 10))
    assert order.status == OrderStatus.REJECTED
    with pytest.raises(ValueError):
        broker.fill(order.id, price=100.0)


def test_sell_closes_position_and_returns_cash() -> None:
    broker = FakeBroker(cash=100_000.0)
    buy = broker.submit_order(_buy("AAA", 10))
    broker.fill(buy.id, price=100.0)

    sell = broker.submit_order(
        OrderRequest(symbol="AAA", side=OrderSide.SELL, quantity=10)
    )
    broker.fill(sell.id, price=120.0)
    assert broker.get_positions() == []
    assert broker.get_account().cash == pytest.approx(100_200.0)  # 99k + 10*120


def test_cancel_open_order() -> None:
    broker = FakeBroker()
    order = broker.submit_order(_buy("AAA", 10))
    broker.cancel_order(order.id)
    assert broker.get_order(order.id).status == OrderStatus.CANCELED
    assert broker.list_open_orders() == []


def test_fills_since_filters_by_timestamp() -> None:
    t0 = datetime(2023, 1, 3, 14, 30, tzinfo=UTC)
    t1 = datetime(2023, 1, 4, 14, 30, tzinfo=UTC)
    broker = FakeBroker()
    o1 = broker.submit_order(_buy("AAA", 1))
    broker.fill(o1.id, price=100.0, timestamp=t0)
    o2 = broker.submit_order(_buy("BBB", 1))
    broker.fill(o2.id, price=100.0, timestamp=t1)

    assert len(broker.list_fills()) == 2
    recent = broker.list_fills(since=t1)
    assert len(recent) == 1
    assert recent[0].symbol == "BBB"


def test_clock_reports_open_state() -> None:
    broker = FakeBroker(is_open=False)
    assert broker.get_clock().is_open is False
    broker.set_open(True)
    assert broker.get_clock().is_open is True


def test_order_request_rejects_invalid_input() -> None:
    """The order contract is enforced at construction: non-empty symbol and a
    finite, positive quantity."""
    with pytest.raises(ValueError):
        OrderRequest(symbol="", side=OrderSide.BUY, quantity=1)
    with pytest.raises(ValueError):
        OrderRequest(symbol="AAA", side=OrderSide.BUY, quantity=0)
    with pytest.raises(ValueError):
        OrderRequest(symbol="AAA", side=OrderSide.BUY, quantity=-5)
    with pytest.raises(ValueError):
        OrderRequest(symbol="AAA", side=OrderSide.BUY, quantity=float("nan"))
