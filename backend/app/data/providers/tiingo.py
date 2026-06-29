"""Tiingo daily-EOD market-data provider.

Implements :class:`MarketDataProvider` against Tiingo's daily prices endpoint,
mapping the vendor response — raw OHLCV plus vendor-computed ``adjClose`` /
``divCash`` / ``splitFactor`` — into the normalized ``PROVIDER_COLUMNS`` frame.
Raw OHLC and ``adj_close`` are stored as-is; the existing ``db_loader`` ratio
mechanism does the OHLC adjustment downstream, so nothing below this layer
changes (decision 2.4 of the M2 plan: trust the vendor back-adjusted series, do
not re-derive it).

The API key is read from the environment via ``Settings`` (never a literal). The
HTTP client is injectable so the provider is unit-testable without network
access; the default client uses the standard library (``urllib``) and adds no
new dependency.

Licensing: Tiingo standard data is internal-use-only. This provider feeds the
local research database; raw vendor bars are never re-exposed through a public
API. Honor that constraint on any future public deployment.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Protocol

import pandas as pd

from app.data.providers.base import PROVIDER_COLUMNS, MarketDataProvider

DEFAULT_BASE_URL = "https://api.tiingo.com"

# Documented free-tier limits (per the roadmap): 50 req/hr, 1000/day,
# 500 symbols/mo. We throttle between requests and fail loud on HTTP 429 rather
# than retry-storm. Surfaced here for callers building a backfill loop.
FREE_TIER_LIMITS = "50 req/hr, 1000 req/day, 500 symbols/mo"

# Mapping from Tiingo response keys to our normalized column names.
_VENDOR_FIELD_MAP = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "adjClose": "adj_close",
    "divCash": "div_cash",
    "splitFactor": "split_factor",
}


class TiingoError(Exception):
    """Tiingo request failed (network, auth, or malformed response)."""


class TiingoRateLimitError(TiingoError):
    """Tiingo returned HTTP 429 — the free-tier rate limit was exceeded."""


class TiingoAuthError(TiingoError):
    """Tiingo rejected the API key (HTTP 401/403)."""


class _Response(Protocol):
    """Minimal HTTP-response shape the provider depends on (httpx/requests-like)."""

    status_code: int

    def json(self) -> Any: ...


class _HttpClient(Protocol):
    """Minimal HTTP-client shape; injectable so tests need no network."""

    def get(self, url: str, params: dict[str, str]) -> _Response: ...


class _UrllibResponse:
    """Adapts a urllib result to the :class:`_Response` shape."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return json.loads(self._body) if self._body else []


class _UrllibClient:
    """Default standard-library HTTP client (no third-party dependency)."""

    def __init__(self, timeout_s: float = 30.0) -> None:
        self._timeout_s = timeout_s

    def get(self, url: str, params: dict[str, str]) -> _Response:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(f"{url}?{query}", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as resp:
                body = resp.read().decode("utf-8")
                return _UrllibResponse(resp.status, body)
        except urllib.error.HTTPError as exc:
            # Surface the status so the provider can map it to a typed error.
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return _UrllibResponse(exc.code, body)
        except urllib.error.URLError as exc:
            raise TiingoError(f"Tiingo network error: {exc.reason}") from exc


class TiingoProvider(MarketDataProvider):
    """Market-data provider backed by Tiingo's daily EOD endpoint.

    Parameters
    ----------
    api_key:
        Tiingo API token, sourced from the environment. Required; an empty key
        raises immediately so the caller falls back to the offline provider.
    base_url:
        API base URL (override only in tests).
    client:
        Injected HTTP client (httpx/requests-like ``.get(url, params)``). The
        default uses the standard library, so no network occurs in unit tests
        that pass a fake client.
    min_interval_s:
        Minimum wall-clock spacing between requests for simple client-side
        throttling. Defaults to 0 (no sleep) so tests are fast; a real backfill
        sets this to respect the free-tier limits.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        client: _HttpClient | None = None,
        min_interval_s: float = 0.0,
    ) -> None:
        if not api_key:
            raise TiingoError(
                "Tiingo API key is required (set TIINGO_API_KEY). "
                "Use the offline provider when no key is configured."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or _UrllibClient()
        self._min_interval_s = min_interval_s
        self._last_request_monotonic: float | None = None

    def fetch_daily(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Return daily OHLCV + vendor adjustment fields for *symbol* over [start, end].

        Maps ``adjClose → adj_close``, ``divCash → div_cash``,
        ``splitFactor → split_factor`` and leaves raw OHLC untouched; the loader
        applies the adjustment ratio downstream.

        Raises ``TiingoRateLimitError`` on HTTP 429, ``TiingoAuthError`` on
        401/403, and ``TiingoError`` on any other transport or mapping problem.
        """
        self._throttle()
        url = f"{self._base_url}/tiingo/daily/{urllib.parse.quote(symbol)}/prices"
        params = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "format": "json",
            "token": self._api_key,
        }
        response = self._client.get(url, params)
        self._raise_for_status(response, symbol)

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise TiingoError(f"Tiingo returned non-JSON response for {symbol}.") from exc

        return _frame_from_payload(payload, symbol)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """Sleep so consecutive requests are at least ``min_interval_s`` apart."""
        if self._min_interval_s <= 0.0:
            self._last_request_monotonic = time.monotonic()
            return
        now = time.monotonic()
        if self._last_request_monotonic is not None:
            elapsed = now - self._last_request_monotonic
            wait = self._min_interval_s - elapsed
            if wait > 0:
                time.sleep(wait)
        self._last_request_monotonic = time.monotonic()

    @staticmethod
    def _raise_for_status(response: _Response, symbol: str) -> None:
        status = response.status_code
        if status == 200:
            return
        if status == 429:
            raise TiingoRateLimitError(
                f"Tiingo rate limit hit (HTTP 429) for {symbol}; "
                f"respect free-tier limits ({FREE_TIER_LIMITS})."
            )
        if status in (401, 403):
            raise TiingoAuthError(
                f"Tiingo rejected the API key (HTTP {status}) for {symbol}."
            )
        raise TiingoError(f"Tiingo request for {symbol} failed with HTTP {status}.")


def _empty_provider_frame() -> pd.DataFrame:
    """An empty frame with exactly the PROVIDER_COLUMNS (for empty date ranges)."""
    return pd.DataFrame({col: pd.Series(dtype="float64") for col in PROVIDER_COLUMNS})


def _frame_from_payload(payload: Any, symbol: str) -> pd.DataFrame:
    """Map a Tiingo daily-prices JSON payload into a normalized provider frame."""
    if not isinstance(payload, list):
        raise TiingoError(f"Unexpected Tiingo payload for {symbol} (expected a list).")
    if not payload:
        return _empty_provider_frame()

    records: list[dict[str, Any]] = []
    for entry in payload:
        if "date" not in entry:
            raise TiingoError(f"Tiingo bar for {symbol} is missing the 'date' field.")
        missing = [k for k in _VENDOR_FIELD_MAP if k not in entry]
        if missing:
            raise TiingoError(
                f"Tiingo bar for {symbol} is missing field(s): {', '.join(missing)}."
            )
        # Daily bars: take the calendar date only, tz-naive, matching the offline
        # provider and the tz-naive MarketData.timestamp column.
        record: dict[str, Any] = {"timestamp": pd.Timestamp(str(entry["date"])[:10])}
        for vendor_key, col in _VENDOR_FIELD_MAP.items():
            record[col] = float(entry[vendor_key])
        records.append(record)

    frame = pd.DataFrame.from_records(records)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    # Return columns in the canonical order.
    return frame[PROVIDER_COLUMNS]
