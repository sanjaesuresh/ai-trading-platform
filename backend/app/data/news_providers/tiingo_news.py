"""Tiingo news provider (Phase 5 M1).

Implements :class:`NewsProvider` against Tiingo's news endpoint, mapping the
vendor response into the normalized ``NEWS_COLUMNS`` frame.

Reuses the market-data Tiingo plumbing verbatim — the same API key (sourced from
``Settings.tiingo_api_key``), the same injectable HTTP client, and the same typed
error mapping (``TiingoError`` / ``TiingoRateLimitError`` / ``TiingoAuthError``)
— so callers handle news and price failures with one error vocabulary. Only the
endpoint, the field mapping, and the first-seen (``crawlDate``) handling are new.

Licensing: Tiingo news is a premium add-on and its terms are internal-use-only.
This provider feeds the local research database; raw vendor article text is never
re-exposed through a public API. The M7 UI surfaces headlines only after the
licensing/display review in the plan's risk section. Honor that on any future
public deployment.
"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

import pandas as pd

from app.data.news_providers.base import NewsProvider, build_news_frame
from app.data.providers.tiingo import (
    DEFAULT_BASE_URL,
    TiingoError,
    TiingoProvider,
    _HttpClient,
    _UrllibClient,
)

# Mapping from Tiingo news response keys to our contract field names. ``id`` and
# ``publishedDate`` are required; ``crawlDate`` is Tiingo's first-seen instant
# (when it crawled the article) and is the contract's first_seen_at.
_VENDOR_FIELD_MAP = {
    "title": "headline",
    "description": "body",
    "source": "source",
    "url": "url",
}


class TiingoNewsProvider(NewsProvider):
    """News provider backed by Tiingo's news endpoint.

    Parameters
    ----------
    api_key:
        Tiingo API token from the environment. Required; an empty key raises so
        the caller falls back to the offline provider.
    base_url:
        API base URL (override only in tests).
    client:
        Injected HTTP client (``.get(url, params, headers)``). The default uses
        the standard library, so no network occurs in unit tests with a fake.
    min_interval_s:
        Minimum wall-clock spacing between requests for client-side throttling.
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
                "Use the offline news provider when no key is configured."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or _UrllibClient()
        self._min_interval_s = min_interval_s
        self._last_request_monotonic: float | None = None

    @property
    def name(self) -> str:
        return "tiingo_news"

    def fetch_news(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Return Tiingo news items for *symbol* over [*start*, *end*].

        Maps ``id → item_id``, ``publishedDate → published_at``,
        ``crawlDate → first_seen_at``, ``title → headline``,
        ``description → body``. Raises ``TiingoRateLimitError`` on HTTP 429,
        ``TiingoAuthError`` on 401/403, and ``TiingoError`` on any other
        transport or mapping problem.
        """
        self._throttle()
        url = f"{self._base_url}/tiingo/news"
        params = {
            "tickers": symbol.lower(),
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        }
        # Send the key as an auth header, never a query param, so it cannot land
        # in proxy/access logs.
        headers = {"Authorization": f"Token {self._api_key}"}
        response = self._client.get(url, params, headers)
        # Reuse the market-data provider's status→error mapping verbatim.
        TiingoProvider._raise_for_status(response, symbol)

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise TiingoError(
                f"Tiingo returned non-JSON news for {symbol}."
            ) from exc

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


def _frame_from_payload(payload: Any, symbol: str) -> pd.DataFrame:
    """Map a Tiingo news JSON payload into a normalized news frame."""
    if not isinstance(payload, list):
        raise TiingoError(
            f"Unexpected Tiingo news payload for {symbol} (expected a list)."
        )

    records: list[dict[str, Any]] = []
    for entry in payload:
        if "id" not in entry:
            raise TiingoError(f"Tiingo news item for {symbol} is missing 'id'.")
        if "publishedDate" not in entry:
            raise TiingoError(
                f"Tiingo news item for {symbol} is missing 'publishedDate'."
            )
        record: dict[str, Any] = {
            "item_id": entry["id"],
            "published_at": entry["publishedDate"],
            # crawlDate is Tiingo's first-seen; fall back to publish if absent.
            "first_seen_at": entry.get("crawlDate") or entry["publishedDate"],
        }
        for vendor_key, col in _VENDOR_FIELD_MAP.items():
            record[col] = entry.get(vendor_key, "")
        records.append(record)

    return build_news_frame(records, symbol)
