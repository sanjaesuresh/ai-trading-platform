"""The ``BrokerPort`` contract and its value types (Phase 3, M2).

A minimal, provider-agnostic broker interface: submit / cancel / read orders,
read positions, read cash and buying power, read recent fills, and read the
market clock. The daily paper-trading runner (M3) depends only on this contract;
both the real ``AlpacaPaperBroker`` and the deterministic ``FakeBroker`` implement
it, so the service and reconciliation logic are fully unit-testable with no
network or keys.

Enum *values* use the broker wire vocabulary (lowercase, e.g. ``"buy"``,
``"opg"``) so the Alpaca adapter maps with no translation table; the
portfolio core's ``"BUY"``/``"SELL"`` strings are mapped at the M3 seam.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    """Time-in-force. ``OPG`` (opening auction / market-on-open) is the Phase 3
    default: it targets the official opening print, the same price the backtest
    models as the next-bar open (plan §3.2)."""

    DAY = "day"
    OPG = "opg"
    CLS = "cls"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class OrderStatus(StrEnum):
    """Normalized order lifecycle states. Maps the Alpaca status vocabulary;
    anything unrecognized maps to ``UNKNOWN`` rather than being silently dropped.
    """

    NEW = "new"
    PENDING_NEW = "pending_new"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
        }

    @property
    def is_open(self) -> bool:
        return self in {
            OrderStatus.NEW,
            OrderStatus.PENDING_NEW,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.PENDING_CANCEL,
        }


# --- Value types ------------------------------------------------------------


@dataclass(frozen=True)
class OrderRequest:
    """A request to place one order.

    ``client_order_id`` is a caller-supplied idempotency key: the runner derives
    a deterministic id per (deployment, symbol, trading day) so a retried run
    reconciles to the existing order rather than duplicating it.
    """

    symbol: str
    side: OrderSide
    quantity: float
    type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.OPG
    client_order_id: str | None = None
    limit_price: float | None = None

    def __post_init__(self) -> None:
        # Enforce the order contract here so neither broker nor the wire ever sees
        # an empty symbol or a non-positive / non-finite quantity.
        if not self.symbol or not self.symbol.strip():
            raise ValueError("OrderRequest.symbol must be a non-empty symbol.")
        q = float(self.quantity)
        if not math.isfinite(q) or q <= 0.0:
            raise ValueError(
                f"OrderRequest.quantity must be finite and > 0 (got {self.quantity!r})."
            )


@dataclass(frozen=True)
class BrokerOrder:
    id: str
    client_order_id: str | None
    symbol: str
    side: OrderSide
    quantity: float
    filled_quantity: float
    status: OrderStatus
    type: OrderType
    time_in_force: TimeInForce
    submitted_at: datetime | None = None
    filled_avg_price: float | None = None


@dataclass(frozen=True)
class BrokerFill:
    order_id: str
    client_order_id: str | None
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    timestamp: datetime


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    quantity: float
    avg_entry_price: float
    market_value: float
    current_price: float


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    buying_power: float
    equity: float
    currency: str = "USD"


@dataclass(frozen=True)
class MarketClock:
    timestamp: datetime
    is_open: bool
    next_open: datetime | None = None
    next_close: datetime | None = None


# --- Errors -----------------------------------------------------------------


class BrokerError(Exception):
    """A broker request failed (network, auth, rate limit, or malformed response)."""


class BrokerAuthError(BrokerError):
    """The broker rejected the API credentials (HTTP 401/403)."""


class BrokerRateLimitError(BrokerError):
    """The broker returned HTTP 429 — too many requests."""


class BrokerRequestError(BrokerError):
    """The broker rejected the request (e.g. HTTP 4xx other than auth/rate)."""


class OrderNotFoundError(BrokerError):
    """No order matched the given id."""


# --- Interface --------------------------------------------------------------


class BrokerPort(ABC):
    """The contract the rest of Phase 3 depends on. Alpaca is the source of truth
    for fills, positions, and cash; implementations expose broker state, they do
    not invent it."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short broker identifier (e.g. ``"alpaca_paper"``, ``"fake"``)."""

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> BrokerOrder:
        """Place an order and return the broker's acknowledgement."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        """Request cancellation of an open order."""

    @abstractmethod
    def get_order(self, order_id: str) -> BrokerOrder:
        """Read one order by broker id. Raises ``OrderNotFoundError`` if unknown."""

    @abstractmethod
    def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        """Read one order by client id, or ``None`` if no such order exists.

        The reconciliation path uses this to decide whether a deterministic
        client id was already submitted (idempotency)."""

    @abstractmethod
    def list_open_orders(self) -> list[BrokerOrder]:
        """All currently-open orders."""

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        """All open positions reported by the broker."""

    @abstractmethod
    def get_account(self) -> AccountSnapshot:
        """Cash, buying power, and equity reported by the broker."""

    @abstractmethod
    def list_fills(self, since: datetime | None = None) -> list[BrokerFill]:
        """Recent fills, optionally only those at/after ``since``."""

    @abstractmethod
    def get_clock(self) -> MarketClock:
        """Current market clock / open state."""
