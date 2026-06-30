"""Date-keyed purged/embargoed walk-forward: the Phase 4 leakage keystone tests.

The single most important correctness property of the phase: for every split — outer
train/test AND inner train/validation — no training row's H-day label horizon reaches
into the held-out window, for any pooled symbol.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.feature_engineering import add_technical_indicators
from app.evaluation.walk_forward import (
    generate_purged_splits,
    inner_validation_split,
)
from app.ml.features import (
    COL_DECISION_TS,
    COL_LABEL_END_TS,
    FeatureLabelSpec,
    build_pooled_panel,
)

HORIZON = 5
_SPLIT_KW = {
    "horizon": HORIZON,
    "in_sample_dates": 60,
    "out_sample_dates": 20,
    "step_dates": 20,
}


def _featured(rows: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, rows))
    close = np.maximum(close, 1.0)
    raw = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-02", periods=rows, freq="B"),
            "open": close * (1.0 + rng.normal(0, 0.002, rows)),
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": rng.integers(1_000, 5_000, rows).astype(float),
        }
    )
    return add_technical_indicators(raw)


def _panel() -> pd.DataFrame:
    frames = {"SPY": _featured(300, 1), "AAPL": _featured(300, 2)}
    spec = FeatureLabelSpec(horizon=HORIZON, deadband=0.0)
    pooled, _ = build_pooled_panel(frames, spec=spec)
    return pooled


def test_splits_are_produced() -> None:
    splits = generate_purged_splits(_panel(), **_SPLIT_KW)
    assert splits


def test_no_train_label_reaches_into_test_window() -> None:
    panel = _panel()
    label_end = panel[COL_LABEL_END_TS].to_numpy()
    for split in generate_purged_splits(panel, **_SPLIT_KW):
        train_label_end = label_end[split.train_idx]
        assert (train_label_end < np.datetime64(split.test_start)).all()


def test_train_and_test_do_not_overlap() -> None:
    panel = _panel()
    for split in generate_purged_splits(panel, **_SPLIT_KW):
        assert set(split.train_idx.tolist()).isdisjoint(split.test_idx.tolist())


def test_every_test_bar_is_after_every_train_bar() -> None:
    panel = _panel()
    decision = panel[COL_DECISION_TS].to_numpy()
    for split in generate_purged_splits(panel, **_SPLIT_KW):
        assert decision[split.train_idx].max() < decision[split.test_idx].min()


def test_boundary_is_calendar_global_across_symbols() -> None:
    # The same date boundary applies to both symbols, so a test window holds both.
    panel = _panel()
    splits = generate_purged_splits(panel, **_SPLIT_KW)
    sym = panel["symbol"].to_numpy()
    assert any(set(sym[s.test_idx.tolist()]) == {"AAPL", "SPY"} for s in splits)


def test_purge_counter_is_recorded() -> None:
    panel = _panel()
    # With embargo defaulting to the horizon, every split removes the overlapping
    # tail of training labels — the counters make that auditable.
    splits = generate_purged_splits(panel, **_SPLIT_KW)
    assert all(s.n_purged >= 0 and s.n_embargoed >= 0 for s in splits)
    assert any(s.n_purged > 0 or s.n_embargoed > 0 for s in splits)


def test_inner_validation_split_is_also_leakage_safe() -> None:
    panel = _panel()
    decision = panel[COL_DECISION_TS].to_numpy()
    label_end = panel[COL_LABEL_END_TS].to_numpy()
    checked = 0
    for split in generate_purged_splits(panel, **_SPLIT_KW):
        inner_train, val = inner_validation_split(
            panel, split.train_idx, horizon=HORIZON
        )
        if inner_train.size == 0 or val.size == 0:
            continue
        checked += 1
        val_start = decision[val].min()
        assert (label_end[inner_train] < val_start).all()
        assert set(inner_train.tolist()).isdisjoint(val.tolist())
        assert decision[inner_train].max() < decision[val].min()
    assert checked > 0


def test_wider_embargo_removes_more_training_rows() -> None:
    panel = _panel()
    small = generate_purged_splits(panel, embargo=1, **_SPLIT_KW)
    big = generate_purged_splits(panel, embargo=40, **_SPLIT_KW)
    by_start_small = {s.test_start: s.train_idx.size for s in small}
    by_start_big = {s.test_start: s.train_idx.size for s in big}
    common = set(by_start_small) & set(by_start_big)
    assert common
    # A wider embargo never keeps more training rows, and strictly fewer somewhere.
    assert all(by_start_big[d] <= by_start_small[d] for d in common)
    assert any(by_start_big[d] < by_start_small[d] for d in common)


def test_keystone_holds_for_misaligned_symbol_calendars() -> None:
    # SPY full grid; AAPL starts later and has gaps. The calendar-global boundary and
    # the purge must still admit no training label into the held-out window.
    spy = _featured(300, 1)
    aapl_full = _featured(300, 2)
    aapl_full["timestamp"] = pd.date_range("2020-02-14", periods=300, freq="B")
    aapl = aapl_full.iloc[::7].reset_index(drop=True)  # punch holes in the calendar
    spec = FeatureLabelSpec(horizon=HORIZON, deadband=0.0)
    panel, _ = build_pooled_panel({"SPY": spy, "AAPL": aapl}, spec=spec)

    label_end = panel[COL_LABEL_END_TS].to_numpy()
    splits = generate_purged_splits(panel, **_SPLIT_KW)
    assert splits
    for split in splits:
        assert (label_end[split.train_idx] < np.datetime64(split.test_start)).all()


def test_empty_panel_yields_no_splits() -> None:
    empty, _ = build_pooled_panel({})
    assert generate_purged_splits(empty, horizon=HORIZON) == []
