"""Unit tests for TiingoNewsProvider against a mocked HTTP client.

DB-free and network-free: a fake client returns canned payloads, so these run
without Docker or a Tiingo key. Mirrors test_tiingo_provider.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from app.data.news_providers.base import NEWS_COLUMNS
from app.data.news_providers.tiingo_news import TiingoNewsProvider
from app.data.providers.tiingo import (
    TiingoAuthError,
    TiingoError,
    TiingoRateLimitError,
)


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


def _article(
    item_id: int,
    published: str,
    *,
    crawl: str | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": item_id,
        "title": f"Headline {item_id}",
        "description": "Body summary.",
        "url": "https://example.test/news",
        "publishedDate": published,
        "source": "tiingo-wire",
        "tickers": ["aapl"],
    }
    if crawl is not None:
        rec["crawlDate"] = crawl
    return rec


def _provider(client: _FakeClient) -> TiingoNewsProvider:
    return TiingoNewsProvider("test-key", base_url="https://example.test", client=client)


# --- shape / mapping ---


def test_frame_has_exact_news_columns() -> None:
    client = _FakeClient(payload=[_article(1, "2023-01-02T13:30:00Z")])
    frame = _provider(client).fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert list(frame.columns) == NEWS_COLUMNS


def test_field_mapping_and_tz() -> None:
    client = _FakeClient(
        payload=[_article(7, "2023-01-02T13:30:00+00:00", crawl="2023-01-02T13:40:00Z")]
    )
    frame = _provider(client).fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    row = frame.iloc[0]
    assert row["item_id"] == "7"
    assert row["symbol"] == "AAPL"
    assert row["headline"] == "Headline 7"
    assert row["body"] == "Body summary."
    assert row["published_at"] == pd.Timestamp("2023-01-02T13:30:00Z")
    assert row["first_seen_at"] == pd.Timestamp("2023-01-02T13:40:00Z")
    assert str(frame["published_at"].dt.tz) == "UTC"


def test_crawl_date_maps_to_first_seen() -> None:
    client = _FakeClient(
        payload=[_article(1, "2023-01-02T13:30:00Z", crawl="2023-01-03T09:00:00Z")]
    )
    frame = _provider(client).fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert frame.iloc[0]["first_seen_at"] == pd.Timestamp("2023-01-03T09:00:00Z")


def test_missing_crawl_date_falls_back_to_published() -> None:
    client = _FakeClient(payload=[_article(1, "2023-01-02T13:30:00Z")])
    frame = _provider(client).fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    row = frame.iloc[0]
    assert row["first_seen_at"] == row["published_at"]


def test_empty_payload_returns_empty_frame() -> None:
    frame = _provider(_FakeClient(payload=[])).fetch_news(
        "AAPL", date(2023, 1, 1), date(2023, 12, 31)
    )
    assert frame.empty
    assert list(frame.columns) == NEWS_COLUMNS


def test_sorted_by_published_at() -> None:
    client = _FakeClient(
        payload=[
            _article(2, "2023-03-01T10:00:00Z"),
            _article(1, "2023-01-01T10:00:00Z"),
        ]
    )
    frame = _provider(client).fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert list(frame["item_id"]) == ["1", "2"]


# --- auth / errors ---


def test_auth_header_set_and_key_absent_from_url() -> None:
    client = _FakeClient(payload=[_article(1, "2023-01-02T13:30:00Z")])
    _provider(client).fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    url, params, headers = client.calls[0]
    assert headers == {"Authorization": "Token test-key"}
    assert "test-key" not in url
    assert "test-key" not in str(params)
    assert params["tickers"] == "aapl"


def test_429_raises_rate_limit_error() -> None:
    with pytest.raises(TiingoRateLimitError, match="429"):
        _provider(_FakeClient(status_code=429)).fetch_news(
            "AAPL", date(2023, 1, 1), date(2023, 12, 31)
        )


def test_401_raises_auth_error() -> None:
    with pytest.raises(TiingoAuthError):
        _provider(_FakeClient(status_code=401)).fetch_news(
            "AAPL", date(2023, 1, 1), date(2023, 12, 31)
        )


def test_missing_api_key_raises() -> None:
    with pytest.raises(TiingoError):
        TiingoNewsProvider("")


def test_item_missing_id_raises() -> None:
    payload = [{"title": "t", "publishedDate": "2023-01-02T13:30:00Z"}]
    with pytest.raises(TiingoError):
        _provider(_FakeClient(payload=payload)).fetch_news(
            "AAPL", date(2023, 1, 1), date(2023, 12, 31)
        )


def test_non_list_payload_raises() -> None:
    with pytest.raises(TiingoError):
        _provider(_FakeClient(payload={"bad": "shape"})).fetch_news(
            "AAPL", date(2023, 1, 1), date(2023, 12, 31)
        )


def test_idempotent() -> None:
    payload = [_article(1, "2023-01-02T13:30:00Z")]
    a = _provider(_FakeClient(payload=payload)).fetch_news(
        "AAPL", date(2023, 1, 1), date(2023, 12, 31)
    )
    b = _provider(_FakeClient(payload=payload)).fetch_news(
        "AAPL", date(2023, 1, 1), date(2023, 12, 31)
    )
    pd.testing.assert_frame_equal(a, b)
