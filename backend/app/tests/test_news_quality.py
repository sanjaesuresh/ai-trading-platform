"""Unit tests for the news data-quality gate (DB-free, network-free)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from app.data.news_providers.base import NEWS_COLUMNS, build_news_frame
from app.data.news_quality import check_and_clean_news

_NOW = datetime(2023, 6, 1, tzinfo=UTC)


def _frame(records: list[dict], symbol: str = "AAPL") -> pd.DataFrame:
    return build_news_frame(records, symbol)


def _rec(item_id: str, published: str, **kw) -> dict:
    rec = {
        "item_id": item_id,
        "published_at": published,
        "first_seen_at": kw.get("first_seen_at", published),
        "headline": kw.get("headline", f"h-{item_id}"),
        "body": kw.get("body", f"b-{item_id}"),
        "source": "wire",
        "url": "https://x",
    }
    return rec


def test_clean_frame_passes_and_keeps_all() -> None:
    frame = _frame([_rec("a", "2023-01-02T10:00:00Z"), _rec("b", "2023-01-03T10:00:00Z")])
    clean, report = check_and_clean_news(frame, now=_NOW)
    assert report.passed
    assert report.items_kept == 2
    assert report.items_dropped == 0
    assert list(clean.columns) == NEWS_COLUMNS


def test_empty_frame_is_valid_not_error() -> None:
    clean, report = check_and_clean_news(_frame([]), now=_NOW)
    assert report.passed
    assert report.items_in == 0
    assert clean.empty


def test_missing_columns_is_blocking() -> None:
    bad = pd.DataFrame({"item_id": ["x"], "symbol": ["AAPL"]})
    clean, report = check_and_clean_news(bad, now=_NOW)
    assert not report.passed
    assert clean.empty
    assert any("Missing" in e for e in report.errors)


def test_future_timestamp_dropped() -> None:
    frame = _frame(
        [
            _rec("a", "2023-01-02T10:00:00Z"),
            _rec("future", "2099-01-01T10:00:00Z"),
        ]
    )
    clean, report = check_and_clean_news(frame, now=_NOW)
    assert report.items_kept == 1
    assert report.items_dropped == 1
    assert "future" not in set(clean["item_id"])


def test_prehistoric_timestamp_dropped() -> None:
    frame = _frame(
        [
            _rec("a", "2023-01-02T10:00:00Z"),
            _rec("old", "1970-01-01T10:00:00Z"),
        ]
    )
    clean, report = check_and_clean_news(frame, now=_NOW)
    assert set(clean["item_id"]) == {"a"}
    assert report.items_dropped == 1


def test_untradable_symbol_dropped_when_allowlist_given() -> None:
    aapl = _frame([_rec("a", "2023-01-02T10:00:00Z")], symbol="AAPL")
    spy = _frame([_rec("b", "2023-01-02T10:00:00Z")], symbol="SPY")
    frame = pd.concat([aapl, spy], ignore_index=True)
    clean, report = check_and_clean_news(frame, valid_symbols=["AAPL"], now=_NOW)
    assert set(clean["symbol"]) == {"AAPL"}
    assert report.items_dropped == 1


def test_exact_duplicate_dropped_revision_kept() -> None:
    # Same id+text twice (dup); same id different body (revision, kept).
    frame = _frame(
        [
            _rec("a", "2023-01-02T10:00:00Z", body="v1"),
            _rec("a", "2023-01-02T10:00:00Z", body="v1"),
            _rec("a", "2023-01-04T10:00:00Z", body="v2-revised", first_seen_at="2023-01-04T10:00:00Z"),
        ]
    )
    clean, report = check_and_clean_news(frame, now=_NOW)
    assert report.items_kept == 2
    bodies = set(clean["body"])
    assert bodies == {"v1", "v2-revised"}


def test_null_required_field_dropped() -> None:
    frame = _frame([_rec("a", "2023-01-02T10:00:00Z")])
    frame.loc[0, "first_seen_at"] = pd.NaT
    # Add a good row so the frame isn't empty afterward.
    good = _frame([_rec("b", "2023-01-03T10:00:00Z")])
    frame = pd.concat([frame, good], ignore_index=True)
    clean, report = check_and_clean_news(frame, now=_NOW)
    assert set(clean["item_id"]) == {"b"}
    assert report.items_dropped == 1


def test_input_not_mutated() -> None:
    frame = _frame([_rec("a", "2023-01-02T10:00:00Z")])
    before = frame.copy()
    check_and_clean_news(frame, now=_NOW)
    pd.testing.assert_frame_equal(frame, before)
