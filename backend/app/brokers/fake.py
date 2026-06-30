"""Deterministic in-memory broker for tests (Phase 3, M2).

Implements the full ``BrokerPort`` so the paper-trading service, the daily runner,
and reconciliation are unit-testable with no network, no keys, and no wall-clock
dependence. Orders are accepted (or rejected for configured symbols) and filled
**on demand** at a controllable price via :meth:`fill` / :meth:`partially_fill`,
so a test drives full fills, partial fills, and rejects deterministically.

Idempotency mirrors a real broker: submitting a second order with an already-seen
``client_order_id`` returns the existing order rather than creating a duplicate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.brokers.base import (
    AccountSnapshot,
    BrokerFill,
    BrokerOrder,
    BrokerPort,
    BrokerPosition,
    MarketClock,
    OrderNotFoundError,
    OrderRequest,
    OrderSide,
    OrderStatus,
)

# A fixed default "now" so tests are reproducible without touching the wall clock.
_DEFAULT_NOW = datetime(2023, 1, 3, 14, 30, tzinfo=UTC)


@dataclass
class _Pos:
    quantity: float
    avg_entry_price: float
    last_price: float


class FakeBroker(BrokerPort):
    def __init__(
        self,
        *,
        cash: float = 100_000.0,
        now: datetime | None = None,
        is_open: bool = True,
        reject_symbols: Iterable[str] = (),
    ) -> None:
        self._cash = float(cash)
        self._now = now or _DEFAULT_NOW
        self._is_open = is_open
        self._reject_symbols = set(reject_symbols)
        self._orders: dict[str, BrokerOrder] = {}
        self._by_client: dict[str, str] = {}
        self._positions: dict[str, _Pos] = {}
        self._fills: list[BrokerFill] = []
        self._seq = 0

    @property
    def name(self) -> str:
        return "fake"

    # --- BrokerPort: writes -------------------------------------------------

    def submit_order(self, request: OrderRequest) -> BrokerOrder:
        # Idempotency: a re-submitted client id returns the existing order.
        if request.client_order_id and request.client_order_id in self._by_client:
            return self._orders[self._by_client[request.client_order_id]]

        self._seq += 1
        order_id = f"fake-{self._seq}"
        status = (
            OrderStatus.REJECTED
            if request.symbol in self._reject_symbols
            else OrderStatus.ACCEPTED
        )
        order = BrokerOrder(
            id=order_id,
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=float(request.quantity),
            filled_quantity=0.0,
            status=status,
            type=request.type,
            time_in_force=request.time_in_force,
            submitted_at=self._now,
            filled_avg_price=None,
        )
        self._orders[order_id] = order
        if request.client_order_id:
            self._by_client[request.client_order_id] = order_id
        return order

    def cancel_order(self, order_id: str) -> None:
        order = self._require(order_id)
        if order.status.is_open:
            self._orders[order_id] = replace(order, status=OrderStatus.CANCELED)

    # --- BrokerPort: reads --------------------------------------------------

    def get_order(self, order_id: str) -> BrokerOrder:
        return self._require(order_id)

    def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        order_id = self._by_client.get(client_order_id)
        return self._orders[order_id] if order_id else None

    def list_open_orders(self) -> list[BrokerOrder]:
        return [o for o in self._orders.values() if o.status.is_open]

    def get_positions(self) -> list[BrokerPosition]:
        out: list[BrokerPosition] = []
        for sym, pos in sorted(self._positions.items()):
            if pos.quantity <= 0.0:
                continue
            out.append(
                BrokerPosition(
                    symbol=sym, quantity=pos.quantity,
                    avg_entry_price=pos.avg_entry_price,
                    market_value=pos.quantity * pos.last_price,
                    current_price=pos.last_price,
                )
            )
        return out

    def get_account(self) -> AccountSnapshot:
        equity = self._cash + sum(
            p.quantity * p.last_price for p in self._positions.values()
        )
        return AccountSnapshot(cash=self._cash, buying_power=self._cash, equity=equity)

    def list_fills(self, since: datetime | None = None) -> list[BrokerFill]:
        if since is None:
            return list(self._fills)
        return [f for f in self._fills if f.timestamp >= since]

    def get_clock(self) -> MarketClock:
        return MarketClock(timestamp=self._now, is_open=self._is_open)

    # --- Test controls ------------------------------------------------------

    def fill(
        self, order_id: str, price: float, timestamp: datetime | None = None
    ) -> BrokerFill:
        """Fully fill the order's remaining quantity at ``price``."""
        order = self._require(order_id)
        remaining = order.quantity - order.filled_quantity
        return self.partially_fill(order_id, remaining, price, timestamp)

    def partially_fill(
        self,
        order_id: str,
        quantity: float,
        price: float,
        timestamp: datetime | None = None,
    ) -> BrokerFill:
        """Fill ``quantity`` of the order at ``price`` (partial or full)."""
        order = self._require(order_id)
        if not order.status.is_open:
            raise ValueError(f"Order {order_id} is not open (status={order.status}).")
        qty = min(float(quantity), order.quantity - order.filled_quantity)
        if qty <= 0.0:
            raise ValueError("Fill quantity must be positive and within the order.")
        ts = timestamp or self._now

        self._apply_to_position(order.symbol, order.side, qty, price)
        fill = BrokerFill(
            order_id=order.id, client_order_id=order.client_order_id,
            symbol=order.symbol, side=order.side, quantity=qty, price=price,
            timestamp=ts,
        )
        self._fills.append(fill)

        new_filled = order.filled_quantity + qty
        # Volume-weighted average fill price across partials.
        prior_notional = (order.filled_avg_price or 0.0) * order.filled_quantity
        avg_price = (prior_notional + qty * price) / new_filled
        status = (
            OrderStatus.FILLED
            if new_filled >= order.quantity - 1e-9
            else OrderStatus.PARTIALLY_FILLED
        )
        self._orders[order_id] = replace(
            order, filled_quantity=new_filled, filled_avg_price=avg_price,
            status=status,
        )
        return fill

    def set_open(self, is_open: bool) -> None:
        self._is_open = is_open

    # --- Internals ----------------------------------------------------------

    def _require(self, order_id: str) -> BrokerOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"No order with id {order_id!r}.")
        return order

    def _apply_to_position(
        self, symbol: str, side: OrderSide, qty: float, price: float
    ) -> None:
        pos = self._positions.get(symbol)
        if side == OrderSide.BUY:
            self._cash -= qty * price
            if pos is None:
                self._positions[symbol] = _Pos(qty, price, price)
            else:
                total_qty = pos.quantity + qty
                pos.avg_entry_price = (
                    pos.avg_entry_price * pos.quantity + price * qty
                ) / total_qty
                pos.quantity = total_qty
                pos.last_price = price
        else:  # SELL
            self._cash += qty * price
            if pos is not None:
                pos.quantity = max(0.0, pos.quantity - qty)
                pos.last_price = price
                if pos.quantity <= 0.0:
                    del self._positions[symbol]
