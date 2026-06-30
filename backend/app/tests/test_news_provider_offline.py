"""Unit tests for OfflineNewsProvider (DB-free, network-free).

The offline provider reads per-symbol JSON fixtures and is the only news
provider the test suite touches, matching the Phase 1 offline-provider
conventions.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.data.news_providers.base import NEWS_COLUMNS, NewsProviderError
from app.data.news_providers.offline import OfflineNewsProvider


def _item(
    item_id: str,
    published_at: str,
    *,
    first_seen_at: str | None = None,
    headline: str = "headline",
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "item_id": item_id,
        "published_at": published_at,
        "headline": headline,
        "body": "body text",
        "source": "TestWire",
        "url": "https://example.test/a",
    }
    if first_seen_at is not None:
        rec["first_seen_at"] = first_seen_at
    return rec


def _write(path: Path, items: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(items), encoding="utf-8")


@pytest.fixture()
def news_dir(tmp_path: Path) -> Path:
    _write(
        tmp_path / "AAPL.json",
        [
            _item("b", "2023-01-04T18:00:00Z", first_seen_at="2023-01-04T18:05:00Z"),
            _item("a", "2023-01-02T13:30:00Z", first_seen_at="2023-01-02T13:31:00Z"),
            _item("c", "2023-02-10T20:00:00Z", first_seen_at="2023-02-10T20:01:00Z"),
        ],
    )
    return tmp_path


@pytest.fixture()
def provider(news_dir: Path) -> OfflineNewsProvider:
    return OfflineNewsProvider(news_dir)


def test_frame_has_exact_news_columns(provider: OfflineNewsProvider) -> None:
    frame = provider.fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert list(frame.columns) == NEWS_COLUMNS


def test_timestamps_are_tz_aware_utc(provider: OfflineNewsProvider) -> None:
    frame = provider.fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert str(frame["published_at"].dt.tz) == "UTC"
    assert str(frame["first_seen_at"].dt.tz) == "UTC"


def test_sorted_by_published_at(provider: OfflineNewsProvider) -> None:
    frame = provider.fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    assert list(frame["item_id"]) == ["a", "b", "c"]
    assert frame["published_at"].is_monotonic_increasing


def test_first_seen_preserved_distinct_from_published(
    provider: OfflineNewsProvider,
) -> None:
    frame = provider.fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    row = frame.loc[frame["item_id"] == "a"].iloc[0]
    assert row["published_at"] == pd.Timestamp("2023-01-02T13:30:00Z")
    assert row["first_seen_at"] == pd.Timestamp("2023-01-02T13:31:00Z")
    assert row["first_seen_at"] > row["published_at"]


def test_first_seen_falls_back_to_published_when_absent(tmp_path: Path) -> None:
    _write(tmp_path / "X.json", [_item("only", "2023-03-01T10:00:00Z")])
    frame = OfflineNewsProvider(tmp_path).fetch_news(
        "X", date(2023, 1, 1), date(2023, 12, 31)
    )
    row = frame.iloc[0]
    assert row["first_seen_at"] == row["published_at"]


def test_date_range_filter_inclusive(provider: OfflineNewsProvider) -> None:
    # Only the January items fall inside this window.
    frame = provider.fetch_news("AAPL", date(2023, 1, 1), date(2023, 1, 31))
    assert list(frame["item_id"]) == ["a", "b"]


def test_missing_symbol_file_returns_empty_frame(provider: OfflineNewsProvider) -> None:
    frame = provider.fetch_news("NOPE", date(2023, 1, 1), date(2023, 12, 31))
    assert frame.empty
    assert list(frame.columns) == NEWS_COLUMNS


def test_idempotent(provider: OfflineNewsProvider) -> None:
    a = provider.fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    b = provider.fetch_news("AAPL", date(2023, 1, 1), date(2023, 12, 31))
    pd.testing.assert_frame_equal(a, b)


def test_path_traversal_in_symbol_raises(news_dir: Path) -> None:
    provider = OfflineNewsProvider(news_dir)
    with pytest.raises(NewsProviderError):
        provider.fetch_news("../secrets", date(2023, 1, 1), date(2023, 12, 31))


def test_missing_base_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(NewsProviderError):
        OfflineNewsProvider(tmp_path / "does-not-exist")


def test_non_list_file_raises(tmp_path: Path) -> None:
    (tmp_path / "BAD.json").write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(NewsProviderError):
        OfflineNewsProvider(tmp_path).fetch_news("BAD", date(2023, 1, 1), date(2023, 12, 31))


def test_item_missing_id_raises(tmp_path: Path) -> None:
    (tmp_path / "BAD.json").write_text(
        json.dumps([{"published_at": "2023-01-02T13:30:00Z"}]), encoding="utf-8"
    )
    with pytest.raises(NewsProviderError):
        OfflineNewsProvider(tmp_path).fetch_news("BAD", date(2023, 1, 1), date(2023, 12, 31))
