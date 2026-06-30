"""Keystone point-in-time correctness tests for the news feature builder (M4/§2).

The analogue of Phase 4's "no training row's label horizon reaches into its test
window" test. If these pass, the news feature for any decision cannot see an
article whose availability time is after the allowed cutoff, and sparse news never
drops an interior decision row.

DB-free, network-free.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.feature_engineering import add_technical_indicators
from app.ml.features import (
    COL_LABEL,
    COL_LABEL_END_TS,
    FEATURE_COLUMNS,
    build_features,
    build_labels,
)
from app.ml.news_features import (
    NEWS_FEATURE_COLUMNS,
    build_news_features,
    session_close_utc,
)


def _bars(n: int, start: str = "2022-01-03") -> pd.DataFrame:
    """A clean OHLCV+indicators frame on business days."""
    ts = pd.date_range(start, periods=n, freq="B")
    close = 100.0 + np.sin(np.arange(n) / 5.0) * 5.0 + np.arange(n) * 0.1
    raw = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000.0 + np.arange(n) * 1000.0,
        }
    )
    return add_technical_indicators(raw)


def _ann(published: str, first_seen: str, sentiment: float, relevance: float) -> dict:
    return {
        "published_at": published,
        "first_seen_at": first_seen,
        "sentiment": sentiment,
        "relevance": relevance,
    }


# --- non-mutation + shape ---


def test_non_mutating_and_appends_columns() -> None:
    frame = _bars(60)
    before = frame.copy()
    out = build_news_features(frame, None)
    pd.testing.assert_frame_equal(frame, before)
    for col in NEWS_FEATURE_COLUMNS:
        assert col in out.columns


def test_no_news_columns_take_quiet_defaults() -> None:
    out = build_news_features(_bars(40), None)
    assert (out["n_has_news"] == 0.0).all()
    assert (out["n_days_since_news"] == 1.0).all()
    assert (out["n_sent_decay"] == 0.0).all()
    assert (out["n_volume_z"] == 0.0).all()


# --- input hardening (fail loud rather than leak from bad input) ---


def test_naive_annotation_timestamps_rejected() -> None:
    frame = _bars(40)
    ann = pd.DataFrame(
        [_ann("2022-02-01T15:00:00", "2022-02-01T15:00:00", 0.5, 1.0)]  # tz-naive
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        build_news_features(frame, ann, embargo=1)


def test_unsorted_frame_rejected() -> None:
    frame = _bars(40).iloc[::-1].reset_index(drop=True)  # descending
    with pytest.raises(ValueError, match="ascending"):
        build_news_features(frame, None)


def test_embargo_zero_rejected() -> None:
    with pytest.raises(ValueError, match="embargo"):
        build_news_features(_bars(10), None, embargo=0)


# --- availability-time cutoff (the leak test) ---


def test_cutoff_uses_availability_and_embargo() -> None:
    frame = _bars(40)
    ts = frame["timestamp"]
    closes = session_close_utc(ts)
    # An item available exactly at bar k's close. With embargo=1, the first bar
    # whose cutoff (= close of bar i-1) is >= this is bar k+1, never bar k.
    k = 20
    avail = closes.iloc[k].isoformat()
    ann = pd.DataFrame([_ann(avail, avail, 0.8, 1.0)])
    out = build_news_features(frame, ann, embargo=1)
    assert out["n_has_news"].iloc[k] == 0.0  # not visible on bar k (leak guard)
    assert out["n_has_news"].iloc[k + 1] == 1.0  # visible on bar k+1


def test_no_feature_sees_future_news() -> None:
    # General invariant: for every row, n_has_news=1 implies an article was
    # available at or before that row's cutoff.
    frame = _bars(50)
    closes = session_close_utc(frame["timestamp"])
    ann = pd.DataFrame(
        [_ann(closes.iloc[i].isoformat(), closes.iloc[i].isoformat(), 0.5, 1.0) for i in (10, 25, 40)]
    )
    out = build_news_features(frame, ann, embargo=1)
    closes_ns = np.asarray(closes.values, dtype="datetime64[ns]").astype("int64")
    avail_ns = closes_ns[[10, 25, 40]]
    for i in range(len(frame)):
        if out["n_has_news"].iloc[i] == 1.0:
            cutoff = closes_ns[i - 1] if i >= 1 else np.iinfo(np.int64).min
            assert (avail_ns <= cutoff).any()


def test_revised_article_lands_at_first_seen_not_publish() -> None:
    # A back-dated revision: published early, first seen late. Availability is the
    # late first-seen, so it must NOT appear at the early publish bar.
    frame = _bars(40)
    closes = session_close_utc(frame["timestamp"])
    publish_bar, first_seen_bar = 5, 25
    ann = pd.DataFrame(
        [_ann(closes.iloc[publish_bar].isoformat(), closes.iloc[first_seen_bar].isoformat(), 0.9, 1.0)]
    )
    out = build_news_features(frame, ann, embargo=1)
    # Nothing visible anywhere at or before the publish bar's neighbourhood.
    assert out["n_has_news"].iloc[: first_seen_bar + 1].sum() == 0.0
    # Visible from the first-seen bar + embargo onward.
    assert out["n_has_news"].iloc[first_seen_bar + 1] == 1.0


def test_after_close_news_shifts_one_bar_vs_before_close() -> None:
    # DST-correct intraday boundary: 15:00 ET (before 16:00 close) is available as
    # of that day's close; 17:00 ET (after close) is not, arriving one bar later.
    frame = _bars(40)
    dates = pd.to_datetime(frame["timestamp"]).dt.normalize()
    day = 20
    before_close = (dates.iloc[day] + pd.Timedelta(hours=15)).tz_localize("America/New_York")
    after_close = (dates.iloc[day] + pd.Timedelta(hours=17)).tz_localize("America/New_York")

    out_before = build_news_features(
        frame, pd.DataFrame([_ann(before_close.isoformat(), before_close.isoformat(), 0.5, 1.0)]), embargo=1
    )
    out_after = build_news_features(
        frame, pd.DataFrame([_ann(after_close.isoformat(), after_close.isoformat(), 0.5, 1.0)]), embargo=1
    )
    first_before = int(np.argmax(out_before["n_has_news"].to_numpy() > 0))
    first_after = int(np.argmax(out_after["n_has_news"].to_numpy() > 0))
    assert first_after == first_before + 1


# --- never-NaN / no-interior-drop on a partially-newsy symbol ---


def test_partially_newsy_symbol_has_no_nan_columns() -> None:
    # Sparse, clustered news with an all-quiet trailing window and a first-article
    # transition — the exact shape that a 0/0 z-score or ratio would punch holes in.
    frame = _bars(120)
    closes = session_close_utc(frame["timestamp"])
    cluster = [60, 61, 62, 90]  # quiet head, a cluster, a long quiet gap, one more
    ann = pd.DataFrame(
        [_ann(closes.iloc[i].isoformat(), closes.iloc[i].isoformat(), 0.3, 0.9) for i in cluster]
    )
    out = build_news_features(frame, ann, embargo=1)
    for col in NEWS_FEATURE_COLUMNS:
        assert not out[col].isna().any(), f"{col} has NaN"


def test_no_interior_decision_row_dropped_vs_price_only() -> None:
    # Replicate the Phase 4 panel keep-mask over price-only vs price+news columns
    # on a partially-newsy symbol. Because news columns are never NaN, adding them
    # to the mask cannot drop any row the price-only mask keeps.
    frame = _bars(120)
    closes = session_close_utc(frame["timestamp"])
    ann = pd.DataFrame(
        [_ann(closes.iloc[i].isoformat(), closes.iloc[i].isoformat(), 0.4, 0.9) for i in (60, 61, 90)]
    )
    news_frame = build_news_features(frame, ann, embargo=1)

    featured = build_features(news_frame).reset_index(drop=True)
    labels = build_labels(featured).reset_index(drop=True)
    labelable = labels[COL_LABEL_END_TS].notna()
    non_neutral = labels[COL_LABEL].notna()

    price_valid = featured[list(FEATURE_COLUMNS)].notna().all(axis=1)
    news_valid = featured[list(NEWS_FEATURE_COLUMNS)].notna().all(axis=1)

    price_keep = price_valid & labelable & non_neutral
    news_keep = price_valid & news_valid & labelable & non_neutral

    assert news_valid.all()  # the keystone invariant
    assert news_keep.equals(price_keep)  # news drops nothing price would keep
    assert int(price_keep.sum()) > 0
