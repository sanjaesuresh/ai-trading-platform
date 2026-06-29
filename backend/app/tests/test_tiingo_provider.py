"""Unit tests for TiingoProvider against a mocked HTTP client.

DB-free and network-free: a fake client returns canned payloads, so these run
under ``pytest`` from ``backend/`` without Docker or a Tiingo key, matching the
Phase 1 test conventions. The one real-network smoke test lives elsewhere and is
opt-in.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from app.data.data_quality import check_data_quality
from app.data.providers.base import PROVIDER_COLUMNS
from app.data.providers.tiingo import (
    TiingoAuthError,
    TiingoError,
    TiingoProvider,
    TiingoRateLimitError,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """Records calls and returns a fixed status + payload."""

    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self.payload = [] if payload is None else payload
        self.calls: list[tuple[str, dict[str, str], dict[str, str] | None]] = []

    def get(
        self, url: str, params: dict[str, str], headers: dict[str, str] | None = None
    ) -> _FakeResponse:
        self.calls.append((url, params, headers))
        return _FakeResponse(self.status_code, self.payload)


def _bar(
    d: str,
    close: float,
    *,
    adj_close: float | None = None,
    div_cash: float = 0.0,
    split_factor: float = 1.0,
) -> dict[str, Any]:
    """One Tiingo daily-prices record (only the fields we map plus 'date')."""
    return {
        "date": f"{d}T00:00:00.000Z",
        "open": close - 1.0,
        "high": close + 1.0,
        "low": close - 2.0,
        "close": close,
        "volume": 1_000_000.0,
        "adjClose": close if adj_close is None else adj_close,
        "divCash": div_cash,
        "splitFactor": split_factor,
    }


def _clean_payload(n: int = 6) -> list[dict[str, Any]]:
    days = pd.date_range("2023-01-02", periods=n, freq="B").strftime("%Y-%m-%d")
    return [_bar(d, 100.0 + i) for i, d in enumerate(days)]


def _provider(client: _FakeClient) -> TiingoProvider:
    return TiingoProvider("test-key", base_url="https://example.test", client=client)


# ---------------------------------------------------------------------------
# Shape / mapping
# ---------------------------------------------------------------------------


def test_frame_has_all_provider_columns() -> None:
    provider = _provider(_FakeClient(payload=_clean_payload()))
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert list(frame.columns) == PROVIDER_COLUMNS


def test_adjustment_fields_mapped() -> None:
    payload = [_bar("2023-01-02", 50.0, adj_close=200.0, div_cash=0.25, split_factor=4.0)]
    provider = _provider(_FakeClient(payload=payload))
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert frame["adj_close"].iloc[0] == 200.0
    assert frame["div_cash"].iloc[0] == 0.25
    assert frame["split_factor"].iloc[0] == 4.0


def test_raw_ohlc_preserved_not_adjusted() -> None:
    """The provider stores raw OHLC; the loader adjusts downstream (decision 2.4)."""
    payload = [_bar("2023-01-02", 50.0, adj_close=200.0, split_factor=4.0)]
    provider = _provider(_FakeClient(payload=payload))
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert frame["close"].iloc[0] == 50.0  # raw, not the 200.0 adjClose
    assert frame["open"].iloc[0] == 49.0


def test_frame_sorted_ascending_with_rangeindex() -> None:
    # Deliberately out-of-order payload.
    payload = [_bar("2023-01-05", 103.0), _bar("2023-01-03", 101.0), _bar("2023-01-04", 102.0)]
    provider = _provider(_FakeClient(payload=payload))
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert frame["timestamp"].is_monotonic_increasing
    assert list(frame.index) == [0, 1, 2]


def test_timestamp_is_tz_naive_calendar_date() -> None:
    provider = _provider(_FakeClient(payload=[_bar("2023-01-02", 100.0)]))
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    ts = frame["timestamp"].iloc[0]
    assert ts.tz is None
    assert ts == pd.Timestamp("2023-01-02")


def test_frame_passes_data_quality_gate() -> None:
    provider = _provider(_FakeClient(payload=_clean_payload()))
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    report = check_data_quality(frame)
    assert report.passed, f"errors: {report.errors}"


def test_request_targets_daily_prices_with_token_and_dates() -> None:
    client = _FakeClient(payload=_clean_payload())
    _provider(client).fetch_daily("AAPL", date(2023, 1, 1), date(2023, 6, 30))
    url, params, headers = client.calls[0]
    assert url.endswith("/tiingo/daily/AAPL/prices")
    # The key travels in the auth header, never in the query string.
    assert headers is not None and headers["Authorization"] == "Token test-key"
    assert "token" not in params
    assert params["startDate"] == "2023-01-01"
    assert params["endDate"] == "2023-06-30"
    assert params["format"] == "json"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_429_raises_rate_limit_error() -> None:
    provider = _provider(_FakeClient(status_code=429))
    with pytest.raises(TiingoRateLimitError, match="429"):
        provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))


def test_401_raises_auth_error() -> None:
    provider = _provider(_FakeClient(status_code=401))
    with pytest.raises(TiingoAuthError):
        provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))


def test_other_status_raises_tiingo_error() -> None:
    provider = _provider(_FakeClient(status_code=500))
    with pytest.raises(TiingoError, match="500"):
        provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))


def test_empty_payload_returns_empty_frame_with_columns() -> None:
    provider = _provider(_FakeClient(payload=[]))
    frame = provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert len(frame) == 0
    assert list(frame.columns) == PROVIDER_COLUMNS


def test_missing_field_raises() -> None:
    bad = [{"date": "2023-01-02T00:00:00.000Z", "open": 1.0}]  # missing close/adj/etc.
    provider = _provider(_FakeClient(payload=bad))
    with pytest.raises(TiingoError, match="missing field"):
        provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))


def test_missing_date_raises() -> None:
    bad = [_bar("2023-01-02", 100.0)]
    del bad[0]["date"]
    provider = _provider(_FakeClient(payload=bad))
    with pytest.raises(TiingoError, match="date"):
        provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))


def test_non_list_payload_raises() -> None:
    provider = _provider(_FakeClient(payload={"detail": "Not Found"}))
    with pytest.raises(TiingoError, match="expected a list"):
        provider.fetch_daily("AAPL", date(2023, 1, 1), date(2023, 12, 31))


def test_empty_api_key_raises() -> None:
    with pytest.raises(TiingoError, match="API key is required"):
        TiingoProvider("")
