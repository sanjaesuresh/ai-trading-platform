"""Tests for the Alpaca paper adapter (Phase 3, M2).

No network: a fake HTTP client records the request the adapter builds and returns
canned JSON, so request shape, response mapping, the paper-only guard, and error
mapping are all verified offline. CI needs no keys.
"""

from __future__ import annotations

from datetime import UTC
from types import SimpleNamespace
from typing import Any

import pytest

from app.brokers.alpaca import (
    ALPACA_PAPER_BASE_URL,
    AlpacaPaperBroker,
    assert_paper_only,
)
from app.brokers.base import (
    BrokerAuthError,
    BrokerError,
    BrokerRateLimitError,
    BrokerRequestError,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)

_ORDER_JSON = {
    "id": "abc-123",
    "client_order_id": "dep1-AAA-2023-01-03",
    "symbol": "AAA",
    "side": "buy",
    "qty": "10",
    "filled_qty": "0",
    "status": "accepted",
    "type": "market",
    "time_in_force": "opg",
    "submitted_at": "2023-01-03T14:30:00Z",
    "filled_avg_price": None,
}


class _FakeResp:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """Records calls and returns whatever ``handler(method, url, params, body)``
    yields as ``(status_code, payload)``."""

    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[SimpleNamespace] = []

    def request(self, method, url, *, params=None, json_body=None, headers=None):
        self.calls.append(
            SimpleNamespace(
                method=method, url=url, params=params, json_body=json_body,
                headers=headers,
            )
        )
        status, payload = self._handler(method, url, params, json_body)
        return _FakeResp(status, payload)


def _broker(handler) -> tuple[AlpacaPaperBroker, _FakeClient]:
    client = _FakeClient(handler)
    return AlpacaPaperBroker("key-id", "secret", client=client), client


# --- Paper-only guard -------------------------------------------------------


def test_assert_paper_only_accepts_paper_rejects_live() -> None:
    assert_paper_only(ALPACA_PAPER_BASE_URL)  # no raise
    with pytest.raises(BrokerError):
        assert_paper_only("https://api.alpaca.markets")  # the LIVE host
    with pytest.raises(BrokerError):
        assert_paper_only("https://example.com")
    with pytest.raises(BrokerError):
        assert_paper_only("http://paper-api.alpaca.markets")  # not https


def test_broker_base_url_is_paper() -> None:
    broker, _ = _broker(lambda *a: (200, _ORDER_JSON))
    assert broker._base_url == ALPACA_PAPER_BASE_URL
    assert "paper-api.alpaca.markets" in broker._base_url
    assert "//api.alpaca.markets" not in broker._base_url


def test_requires_credentials() -> None:
    with pytest.raises(BrokerAuthError):
        AlpacaPaperBroker("", "")
    with pytest.raises(BrokerAuthError):
        AlpacaPaperBroker("key", "")


# --- Request shaping + response mapping ------------------------------------


def test_submit_order_builds_request_and_maps_response() -> None:
    broker, client = _broker(lambda *a: (200, _ORDER_JSON))
    order = broker.submit_order(
        OrderRequest(
            symbol="AAA", side=OrderSide.BUY, quantity=10,
            type=OrderType.MARKET, time_in_force=TimeInForce.OPG,
            client_order_id="dep1-AAA-2023-01-03",
        )
    )
    call = client.calls[0]
    assert call.method == "POST"
    assert call.url == f"{ALPACA_PAPER_BASE_URL}/v2/orders"
    assert call.json_body == {
        "symbol": "AAA", "qty": "10", "side": "buy", "type": "market",
        "time_in_force": "opg", "client_order_id": "dep1-AAA-2023-01-03",
    }
    assert call.headers["APCA-API-KEY-ID"] == "key-id"
    assert call.headers["APCA-API-SECRET-KEY"] == "secret"
    # Mapped response.
    assert order.id == "abc-123"
    assert order.side == OrderSide.BUY
    assert order.status == OrderStatus.ACCEPTED
    assert order.time_in_force == TimeInForce.OPG


def test_account_and_positions_and_clock_map() -> None:
    def handler(method, url, params, body):
        if url.endswith("/v2/account"):
            return 200, {"cash": "99000", "buying_power": "99000", "equity": "100000"}
        if url.endswith("/v2/positions"):
            return 200, [{
                "symbol": "AAA", "qty": "10", "avg_entry_price": "100",
                "market_value": "1000", "current_price": "100",
            }]
        if url.endswith("/v2/clock"):
            return 200, {"timestamp": "2023-01-03T14:30:00Z", "is_open": True}
        return 404, None

    broker, _ = _broker(handler)
    acct = broker.get_account()
    assert acct.cash == pytest.approx(99_000.0)
    assert acct.equity == pytest.approx(100_000.0)

    positions = broker.get_positions()
    assert positions[0].symbol == "AAA"
    assert positions[0].quantity == pytest.approx(10.0)

    assert broker.get_clock().is_open is True


def test_list_fills_passes_after_and_maps_activities() -> None:
    captured = {}

    def handler(method, url, params, body):
        captured["params"] = params
        return 200, [{
            "order_id": "abc-123", "symbol": "AAA", "side": "buy",
            "qty": "10", "price": "100.5",
            "transaction_time": "2023-01-03T14:30:01.123456789Z",
        }]

    broker, _ = _broker(handler)
    from datetime import datetime

    since = datetime(2023, 1, 3, tzinfo=UTC)
    fills = broker.list_fills(since=since)
    assert captured["params"]["activity_types"] == "FILL"
    assert "after" in captured["params"]
    assert fills[0].price == pytest.approx(100.5)
    assert fills[0].symbol == "AAA"
    assert fills[0].timestamp is not None  # nanosecond precision parsed safely


def test_get_order_by_client_id_returns_none_on_404() -> None:
    broker, _ = _broker(lambda *a: (404, None))
    assert broker.get_order_by_client_id("missing") is None


def test_unknown_status_maps_to_unknown() -> None:
    payload = {**_ORDER_JSON, "status": "some_new_status"}
    broker, _ = _broker(lambda *a: (200, payload))
    order = broker.get_order("abc-123")
    assert order.status == OrderStatus.UNKNOWN


@pytest.mark.parametrize(
    "status,exc",
    [
        (429, BrokerRateLimitError),
        (401, BrokerAuthError),
        (403, BrokerAuthError),
        (500, BrokerRequestError),
    ],
)
def test_http_errors_map_to_typed_exceptions(status, exc) -> None:
    broker, _ = _broker(lambda *a: (status, None))
    with pytest.raises(exc):
        broker.get_account()
