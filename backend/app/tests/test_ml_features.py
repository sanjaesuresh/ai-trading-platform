"""Point-in-time feature/label builder: causality, executable anchor, accounting."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.feature_engineering import add_technical_indicators
from app.ml.features import (
    COL_LABEL,
    COL_LABEL_END_TS,
    FEATURE_COLUMNS,
    FeatureLabelSpec,
    build_features,
    build_labels,
    build_pooled_panel,
    build_symbol_panel,
    compute_uniqueness_weights,
    effective_sample_size,
)


def _raw(rows: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, rows))
    close = np.maximum(close, 1.0)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-02", periods=rows, freq="B"),
            "open": close * (1.0 + rng.normal(0, 0.002, rows)),
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": rng.integers(1_000, 5_000, rows).astype(float),
        }
    )


def _featured(rows: int = 200, seed: int = 7) -> pd.DataFrame:
    return add_technical_indicators(_raw(rows, seed))


def test_features_added_and_eventually_valid() -> None:
    out = build_features(_featured())
    for col in FEATURE_COLUMNS:
        assert col in out.columns
        assert not np.isnan(out[col].iloc[-1])


def test_build_features_does_not_mutate_input() -> None:
    frame = _featured()
    snapshot = frame.copy(deep=True)
    build_features(frame)
    pd.testing.assert_frame_equal(frame, snapshot)


def test_features_are_causal() -> None:
    # A feature at bar t must not change when bars after t are altered. Run the whole
    # chain (indicators + features) so an accidental forward-looking transform anywhere
    # would surface.
    rows = 200
    t = 120
    base = build_features(_featured(rows))

    raw = _raw(rows)
    raw.loc[t + 1 :, ["open", "high", "low", "close"]] *= 3.0  # vandalize the future
    raw.loc[t + 1 :, "volume"] *= 10.0
    perturbed = build_features(add_technical_indicators(raw))

    pd.testing.assert_frame_equal(
        base.loc[:t, list(FEATURE_COLUMNS)],
        perturbed.loc[:t, list(FEATURE_COLUMNS)],
    )


def test_label_uses_executable_open_anchor_not_close() -> None:
    # Opens ramp up, closes ramp down. Open-to-open forward return is always positive
    # (label 1); a close-to-close label would be negative. Pins the executable anchor.
    rows = 40
    ts = pd.date_range("2021-01-04", periods=rows, freq="B")
    opens = np.linspace(100.0, 140.0, rows)
    closes = np.linspace(140.0, 100.0, rows)
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "open": opens,
            "high": np.maximum(opens, closes) + 1.0,
            "low": np.minimum(opens, closes) - 1.0,
            "close": closes,
            "volume": np.full(rows, 1_000.0),
        }
    )
    labels = build_labels(frame, horizon=5, deadband=0.0)
    labelable = labels[COL_LABEL].notna()
    assert labelable.any()
    assert (labels.loc[labelable, COL_LABEL] == 1.0).all()


def test_label_horizon_and_anchor_arithmetic() -> None:
    rows = 20
    frame = _raw(rows)
    horizon = 5
    labels = build_labels(frame, horizon=horizon, deadband=0.0)
    # Manually: row N's forward return is open[N+1+H]/open[N+1]-1.
    n = 3
    expected = frame["open"].iloc[n + 1 + horizon] / frame["open"].iloc[n + 1] - 1.0
    expected_label = 1.0 if expected > 0 else 0.0
    assert labels[COL_LABEL].iloc[n] == expected_label
    assert labels[COL_LABEL_END_TS].iloc[n] == frame["timestamp"].iloc[n + 1 + horizon]


def test_label_tail_is_unlabelable() -> None:
    rows = 30
    horizon = 5
    labels = build_labels(_raw(rows), horizon=horizon, deadband=0.0)
    # The final H+1 rows have no exit open -> NaN label and NaN label_end_ts.
    assert labels[COL_LABEL].iloc[-(horizon + 1) :].isna().all()
    assert labels[COL_LABEL_END_TS].iloc[-(horizon + 1) :].isna().all()


def test_deadband_drops_small_moves() -> None:
    rows = 30
    frame = _raw(rows)
    no_band = build_labels(frame, horizon=5, deadband=0.0)[COL_LABEL].notna().sum()
    wide_band = build_labels(frame, horizon=5, deadband=0.5)[COL_LABEL].notna().sum()
    # A wide deadband makes more rows neutral, so fewer survive.
    assert wide_band < no_band


def test_uniqueness_weights_non_overlapping_are_one() -> None:
    entry = np.array([1, 7, 13])
    exit_ = np.array([6, 12, 18])  # disjoint intervals
    w = compute_uniqueness_weights(entry, exit_)
    assert np.allclose(w, 1.0)


def test_uniqueness_weights_overlap_below_one() -> None:
    entry = np.array([1, 2])
    exit_ = np.array([6, 7])  # overlap on bars 2..6
    w = compute_uniqueness_weights(entry, exit_)
    assert np.allclose(w, 3.5 / 6.0)
    assert effective_sample_size(w) < 2.0


def test_symbol_panel_row_accounting() -> None:
    spec = FeatureLabelSpec(horizon=5, deadband=0.0)
    panel, report = build_symbol_panel(_featured(rows=200), symbol="SPY", spec=spec)
    assert report.symbol == "SPY"
    assert report.rows_input == 200
    assert report.rows_final == len(panel)
    # Final rows are feature-valid AND labelable AND non-neutral.
    assert report.rows_final <= report.rows_feature_valid
    assert report.rows_final <= report.rows_labelable
    assert (panel[COL_LABEL].isin([0.0, 1.0])).all()
    assert not panel[list(FEATURE_COLUMNS)].isna().any().any()


def test_pooled_panel_is_time_sorted_and_interleaved() -> None:
    frames = {"SPY": _featured(rows=200, seed=1), "AAPL": _featured(rows=200, seed=2)}
    pooled, reports = build_pooled_panel(frames)
    assert len(reports) == 2
    assert pooled["decision_ts"].is_monotonic_increasing
    # Both symbols present and interleaved (not concatenated end to end).
    assert set(pooled["symbol"].unique()) == {"AAPL", "SPY"}


def test_empty_pooled_panel_has_columns() -> None:
    pooled, reports = build_pooled_panel({})
    assert reports == []
    for col in (COL_LABEL, *FEATURE_COLUMNS):
        assert col in pooled.columns
    assert pooled.empty
