"""Alpaca **paper** trading adapter (Phase 3, M2).

A thin client over Alpaca's paper REST API implementing ``BrokerPort``. The base
URL is fixed to the paper endpoint and validated at construction — there is no
code path, and no configuration, that targets the live (real-money) endpoint.
Live trading is a separate, deliberate Phase 6 decision; this adapter cannot
reach it.

Credentials come from the environment via ``Settings`` (``ALPACA_API_KEY`` /
``ALPACA_SECRET_KEY``), never a literal. The HTTP client is injectable so the
request/response mapping is unit-testable with no network; the default uses the
standard library (``urllib``) and adds no dependency, matching the Tiingo
provider. Alpaca is the source of truth for fills, positions, and cash.

Known paper limitations (documented, directional, not modeled away): Alpaca paper
fills against real quotes and does not simulate dividends, market impact, latency,
or queue position. The platform treats Alpaca as the fill authority while keeping
its own modeled frictions in the backtest; the realized-minus-modeled gap is
measured per fill in M3 (plan §3.2, §13.2).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

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

if TYPE_CHECKING:
    from app.core.config import Settings

# The paper endpoint — fixed. The live host is ``api.alpaca.markets``; it is never
# constructed here, and ``assert_paper_only`` rejects anything but the paper host.
ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_PAPER_HOST = "paper-api.alpaca.markets"

# Documented order-API rate limit (per the roadmap): 200 requests/minute.
RATE_LIMIT_PER_MIN = 200


def assert_paper_only(base_url: str) -> None:
    """Raise unless *base_url* is exactly the Alpaca paper host.

    The structural paper-only gate (plan §7): called at construction and asserted
    by a test, so no configuration or future edit can point the adapter at the
    live endpoint without tripping it.
    """
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "https" or parsed.netloc.lower() != _PAPER_HOST:
        raise BrokerError(
            f"Refusing non-paper Alpaca endpoint {base_url!r}. Phase 3 is "
            f"paper-only over https; the live endpoint is not reachable "
            f"(Phase 6 decision)."
        )


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _HttpClient(Protocol):
    """Minimal HTTP-client shape; injectable so tests need no network."""

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _Response: ...


class _UrllibResponse:
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return json.loads(self._body) if self._body else None


class _UrllibClient:
    """Default standard-library HTTP client (no third-party dependency)."""

    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout_s = timeout_s

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _Response:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as resp:
                body = resp.read().decode("utf-8")
                return _UrllibResponse(resp.status, body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return _UrllibResponse(exc.code, body)
        except urllib.error.URLError as exc:
            raise BrokerError(f"Alpaca network error: {exc.reason}") from exc


class AlpacaPaperBroker(BrokerPort):
    """``BrokerPort`` over Alpaca's paper REST API (paper endpoint only)."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        client: _HttpClient | None = None,
    ) -> None:
        if not api_key or not secret_key:
            raise BrokerAuthError(
                "Alpaca paper credentials are required (set ALPACA_API_KEY and "
                "ALPACA_SECRET_KEY). Use the FakeBroker when no keys are configured."
            )
        # Defense in depth: the base URL is a constant, but assert it anyway so the
        # gate is exercised at construction and can never silently drift.
        assert_paper_only(ALPACA_PAPER_BASE_URL)
        self._base_url = ALPACA_PAPER_BASE_URL
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._client = client or _UrllibClient()

    @property
    def name(self) -> str:
        return "alpaca_paper"

    @classmethod
    def from_settings(
        cls, settings: Settings, *, client: _HttpClient | None = None
    ) -> AlpacaPaperBroker:
        return cls(settings.alpaca_api_key, settings.alpaca_secret_key, client=client)

    # --- BrokerPort: writes -------------------------------------------------

    def submit_order(self, request: OrderRequest) -> BrokerOrder:
        body: dict[str, Any] = {
            "symbol": request.symbol,
            "qty": _format_qty(request.quantity),
            "side": str(request.side),
            "type": str(request.type),
            "time_in_force": str(request.time_in_force),
        }
        if request.client_order_id:
            body["client_order_id"] = request.client_order_id
        if request.limit_price is not None:
            body["limit_price"] = str(request.limit_price)
        payload = self._call("POST", "/v2/orders", json_body=body)
        return _order_from_json(payload)

    def cancel_order(self, order_id: str) -> None:
        self._call("DELETE", f"/v2/orders/{urllib.parse.quote(order_id, safe='')}")

    # --- BrokerPort: reads --------------------------------------------------

    def get_order(self, order_id: str) -> BrokerOrder:
        payload = self._call(
            "GET", f"/v2/orders/{urllib.parse.quote(order_id, safe='')}"
        )
        return _order_from_json(payload)

    def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        try:
            payload = self._call(
                "GET", "/v2/orders:by_client_order_id",
                params={"client_order_id": client_order_id},
            )
        except OrderNotFoundError:
            return None
        return _order_from_json(payload) if payload else None

    def list_open_orders(self) -> list[BrokerOrder]:
        payload = self._call("GET", "/v2/orders", params={"status": "open"})
        return [_order_from_json(o) for o in (payload or [])]

    def get_positions(self) -> list[BrokerPosition]:
        payload = self._call("GET", "/v2/positions")
        return [_position_from_json(p) for p in (payload or [])]

    def get_account(self) -> AccountSnapshot:
        return _account_from_json(self._call("GET", "/v2/account"))

    def list_fills(self, since: datetime | None = None) -> list[BrokerFill]:
        params = {"activity_types": "FILL"}
        if since is not None:
            params["after"] = since.isoformat()
        payload = self._call("GET", "/v2/account/activities", params=params)
        return [_fill_from_activity(a) for a in (payload or [])]

    def get_clock(self) -> MarketClock:
        return _clock_from_json(self._call("GET", "/v2/clock"))

    # --- Internals ----------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        response = self._client.request(
            method, url, params=params, json_body=json_body, headers=self._headers
        )
        self._raise_for_status(response, method, path)
        return response.json()

    @staticmethod
    def _raise_for_status(response: _Response, method: str, path: str) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status == 429:
            raise BrokerRateLimitError(
                f"Alpaca rate limit hit (HTTP 429) on {method} {path}; "
                f"limit is {RATE_LIMIT_PER_MIN} req/min."
            )
        if status in (401, 403):
            raise BrokerAuthError(
                f"Alpaca rejected the credentials (HTTP {status}) on {method} {path}."
            )
        if status == 404:
            raise OrderNotFoundError(f"Alpaca returned 404 on {method} {path}.")
        # Include Alpaca's own error detail (e.g. "insufficient buying power"),
        # truncated. It is the response body — never our request headers — so no
        # credential can appear here; useful for M3 reject reconciliation.
        try:
            detail = str(response.json())[:200]
        except Exception:  # noqa: BLE001 - body may be absent or non-JSON
            detail = ""
        raise BrokerRequestError(
            f"Alpaca request {method} {path} failed with HTTP {status}. {detail}".strip()
        )


def build_paper_broker(
    settings: Settings, *, client: _HttpClient | None = None
) -> AlpacaPaperBroker:
    """Construct the paper broker from settings; raises if keys are absent."""
    return AlpacaPaperBroker.from_settings(settings, client=client)


# --- JSON mapping -----------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    # Alpaca may send nanosecond precision; trim to microseconds for fromisoformat.
    if "." in text:
        head, _, tail = text.partition(".")
        frac = tail
        offset = ""
        for marker in ("+", "-"):
            if marker in tail:
                frac, _, off = tail.partition(marker)
                offset = marker + off
                break
        frac = frac[:6]
        text = f"{head}.{frac}{offset}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _to_float(value: Any) -> float:
    return float(value) if value not in (None, "") else 0.0


def _format_qty(quantity: float) -> str:
    """Format an order quantity for the wire. Whole shares are sent without a
    trailing ``.0`` — Alpaca treats a decimal qty as *fractional*, and fractional
    orders cannot use the opening-auction (OPG) time-in-force this phase relies on.
    """
    q = float(quantity)
    return str(int(q)) if q == int(q) else repr(q)


def _map_status(raw: Any) -> OrderStatus:
    try:
        return OrderStatus(str(raw))
    except ValueError:
        return OrderStatus.UNKNOWN


def _order_from_json(data: dict[str, Any]) -> BrokerOrder:
    return BrokerOrder(
        id=str(data["id"]),
        client_order_id=data.get("client_order_id"),
        symbol=str(data["symbol"]),
        side=OrderSide(str(data["side"])),
        quantity=_to_float(data.get("qty")),
        filled_quantity=_to_float(data.get("filled_qty")),
        status=_map_status(data.get("status")),
        type=OrderType(str(data.get("type", data.get("order_type", "market")))),
        time_in_force=TimeInForce(str(data.get("time_in_force", "opg"))),
        submitted_at=_parse_dt(data.get("submitted_at")),
        filled_avg_price=(
            _to_float(data["filled_avg_price"])
            if data.get("filled_avg_price")
            else None
        ),
    )


def _position_from_json(data: dict[str, Any]) -> BrokerPosition:
    return BrokerPosition(
        symbol=str(data["symbol"]),
        quantity=_to_float(data.get("qty")),
        avg_entry_price=_to_float(data.get("avg_entry_price")),
        market_value=_to_float(data.get("market_value")),
        current_price=_to_float(data.get("current_price")),
    )


def _account_from_json(data: dict[str, Any]) -> AccountSnapshot:
    return AccountSnapshot(
        cash=_to_float(data.get("cash")),
        buying_power=_to_float(data.get("buying_power")),
        equity=_to_float(data.get("equity")),
        currency=str(data.get("currency", "USD")),
    )


def _fill_from_activity(data: dict[str, Any]) -> BrokerFill:
    ts = _parse_dt(data.get("transaction_time")) or _parse_dt(data.get("date"))
    return BrokerFill(
        order_id=str(data.get("order_id", "")),
        client_order_id=data.get("client_order_id"),
        symbol=str(data["symbol"]),
        side=OrderSide(str(data["side"])),
        quantity=_to_float(data.get("qty")),
        price=_to_float(data.get("price")),
        timestamp=ts or datetime.min,
    )


def _clock_from_json(data: dict[str, Any]) -> MarketClock:
    return MarketClock(
        timestamp=_parse_dt(data.get("timestamp")) or datetime.min,
        is_open=bool(data.get("is_open", False)),
        next_open=_parse_dt(data.get("next_open")),
        next_close=_parse_dt(data.get("next_close")),
    )
