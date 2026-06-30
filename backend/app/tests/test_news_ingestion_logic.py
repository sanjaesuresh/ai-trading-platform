"""Unit tests for pure news-ingestion logic (DB-free, network-free)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from app.data.news_ingestion.logic import (
    build_news_audit_summary,
    build_news_upsert_rows,
    compute_incremental_news_slice,
    compute_incremental_news_start,
    content_hash,
)
from app.data.news_providers.base import build_news_frame


def _frame(records: list[dict], symbol: str = "AAPL") -> pd.DataFrame:
    return build_news_frame(records, symbol)


def _rec(item_id: str, published: str, first_seen: str, **kw) -> dict:
    return {
        "item_id": item_id,
        "published_at": published,
        "first_seen_at": first_seen,
        "headline": kw.get("headline", f"h-{item_id}"),
        "body": kw.get("body", f"b-{item_id}"),
        "source": "wire",
        "url": "https://x",
    }


# --- content_hash ---


def test_content_hash_is_stable() -> None:
    assert content_hash("head", "body") == content_hash("head", "body")


def test_content_hash_changes_on_revision() -> None:
    assert content_hash("head", "v1") != content_hash("head", "v2")


def test_content_hash_separates_headline_body_boundary() -> None:
    # No boundary collision: ("ab","c") must differ from ("a","bc").
    assert content_hash("ab", "c") != content_hash("a", "bc")


# --- incremental slice ---


def test_backfill_returns_full_frame() -> None:
    frame = _frame(
        [
            _rec("a", "2023-01-02T10:00:00Z", "2023-01-02T10:00:00Z"),
            _rec("b", "2023-01-03T10:00:00Z", "2023-01-03T10:00:00Z"),
        ]
    )
    out = compute_incremental_news_slice(None, frame)
    assert len(out) == 2


def test_incremental_keeps_only_newer_first_seen() -> None:
    frame = _frame(
        [
            _rec("a", "2023-01-02T10:00:00Z", "2023-01-02T10:00:00Z"),
            _rec("b", "2023-01-03T10:00:00Z", "2023-01-04T10:00:00Z"),
        ]
    )
    cutoff = datetime.fromisoformat("2023-01-03T00:00:00+00:00")
    out = compute_incremental_news_slice(cutoff, frame)
    assert set(out["item_id"]) == {"b"}


def test_incremental_on_empty_is_empty() -> None:
    out = compute_incremental_news_slice(None, _frame([]))
    assert out.empty


def test_incremental_start_backfill_uses_default() -> None:
    assert compute_incremental_news_start(None, date(2015, 1, 1)) == date(2015, 1, 1)


def test_incremental_start_uses_latest_day() -> None:
    latest = datetime.fromisoformat("2023-05-10T18:00:00+00:00")
    assert compute_incremental_news_start(latest, date(2015, 1, 1)) == date(2023, 5, 10)


# --- upsert rows ---


def test_build_upsert_rows_shape_and_hash() -> None:
    frame = _frame([_rec("a", "2023-01-02T10:00:00Z", "2023-01-02T10:05:00Z")])
    rows = build_news_upsert_rows(frame, provider="offline_news")
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "AAPL"
    assert row["item_id"] == "a"
    assert row["provider"] == "offline_news"
    assert row["content_hash"] == content_hash("h-a", "b-a")
    assert isinstance(row["published_at"], datetime)
    assert isinstance(row["first_seen_at"], datetime)


def test_build_upsert_rows_empty() -> None:
    assert build_news_upsert_rows(_frame([]), provider="x") == []


def test_revised_body_gets_distinct_hash_in_rows() -> None:
    frame = _frame(
        [
            _rec("a", "2023-01-02T10:00:00Z", "2023-01-02T10:00:00Z", body="v1"),
            _rec("a", "2023-01-04T10:00:00Z", "2023-01-04T10:00:00Z", body="v2"),
        ]
    )
    rows = build_news_upsert_rows(frame, provider="x")
    hashes = {r["content_hash"] for r in rows}
    assert len(hashes) == 2


# --- audit summary ---


def test_audit_summary_completed() -> None:
    s = build_news_audit_summary(10, 7, 3)
    assert s.status == "completed"
    assert (s.items_fetched, s.items_written, s.items_dropped) == (10, 7, 3)
    assert s.error is None


def test_audit_summary_failed() -> None:
    s = build_news_audit_summary(5, 0, 0, error="boom")
    assert s.status == "failed"
    assert s.error == "boom"
