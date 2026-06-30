"""Broker layer (Phase 3, M2).

A provider-agnostic ``BrokerPort`` contract and its implementations: a real
``AlpacaPaperBroker`` (paper REST only — the live endpoint is structurally
unreachable) and a deterministic in-memory ``FakeBroker`` for tests. The rest of
Phase 3 depends only on ``BrokerPort``, never on Alpaca directly.
"""

from __future__ import annotations

from app.brokers.base import (
    AccountSnapshot,
    BrokerAuthError,
    BrokerError,
    BrokerFill,
    BrokerOrder,
    BrokerPort,
    BrokerPosition,
    BrokerRateLimitError,
    BrokerRequestError,
    MarketClock,
    OrderNotFoundError,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)

__all__ = [
    "AccountSnapshot",
    "BrokerAuthError",
    "BrokerError",
    "BrokerFill",
    "BrokerOrder",
    "BrokerPort",
    "BrokerPosition",
    "BrokerRateLimitError",
    "BrokerRequestError",
    "MarketClock",
    "OrderNotFoundError",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "TimeInForce",
]
