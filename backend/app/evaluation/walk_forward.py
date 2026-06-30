"""Walk-forward split generation (pure logic).

A split is a pair of half-open bar-index windows: a training (in-sample) window
used to choose parameters and a strictly-later test (out-of-sample) window used
to score them. Because the test window always begins at ``train_end`` and ends
no earlier, every test bar is later in time than every train bar — the structural
guarantee against look-ahead. Indicators are backward-looking, so computing them
once over the full series and slicing by these indices introduces no leakage.

Two schemes:
- ``anchored`` (expanding): ``train_start`` stays 0; the in-sample window grows.
- ``rolling``: the in-sample window stays a fixed ``in_sample_size`` long and
  slides forward.

The final out-of-sample window may be shorter than ``out_sample_size`` (it is
clamped to ``n_bars``) so the tail of the series is still evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_SCHEMES = ("anchored", "rolling")


@dataclass(frozen=True)
class WalkForwardSplit:
    """Half-open bar-index bounds for one train/test split.

    ``train_end`` is the first index *not* in the training window; likewise
    ``test_end``. So train is ``[train_start, train_end)`` and test is
    ``[test_start, test_end)`` with ``test_start == train_end``.
    """

    train_start: int
    train_end: int
    test_start: int
    test_end: int


def generate_splits(
    n_bars: int,
    *,
    scheme: str = "anchored",
    in_sample_size: int = 504,
    out_sample_size: int = 126,
    step: int = 126,
) -> list[WalkForwardSplit]:
    """Generate walk-forward splits over ``n_bars`` bars.

    Returns an empty list when ``n_bars`` is too small to form even one in-sample
    window plus one test bar (``n_bars <= in_sample_size``). Raises ``ValueError``
    for an unknown ``scheme``.
    """
    if scheme not in _SCHEMES:
        raise ValueError(f"scheme must be one of {_SCHEMES}, got {scheme!r}.")

    splits: list[WalkForwardSplit] = []
    train_end = in_sample_size
    while train_end < n_bars:
        train_start = 0 if scheme == "anchored" else train_end - in_sample_size
        test_start = train_end
        test_end = min(train_end + out_sample_size, n_bars)
        splits.append(
            WalkForwardSplit(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        train_end += step
    return splits


# ---------------------------------------------------------------------------
# Phase 4: date-keyed, purged-and-embargoed walk-forward for the ML pipeline.
#
# The index splitter above is correct for rule-based strategies whose indicators
# are backward-looking and whose evaluation never trains a model — slicing
# precomputed indicators by index leaks nothing. ML is different: a forward-looking
# H-day label computed inside the training window can reach across the boundary into
# the held-out window, and a pooled model spans several symbols at once. So the ML
# pipeline needs a splitter that (1) keys the train/test boundary to a single
# calendar date applied to *all* symbols (so one symbol's future cannot leak through
# another), (2) purges training rows whose label horizon overlaps the held-out
# window, and (3) embargoes a gap before the held-out window. The same purge+embargo
# applies to the inner train/validation split. This is the correctness keystone of
# Phase 4 (plan §6).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PurgedSplit:
    """One calendar-global, purged-and-embargoed train/test split over a pooled panel.

    ``train_idx``/``test_idx`` are positional indices into the panel (post purge and
    embargo). ``test_start``/``test_end`` are the inclusive calendar bounds of the
    held-out window. The counters record how the raw training set was trimmed so the
    leakage controls are auditable rather than silent.
    """

    train_idx: np.ndarray
    test_idx: np.ndarray
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    n_train_raw: int
    n_purged: int
    n_embargoed: int


def _date_windows(
    dates: list[pd.Timestamp],
    *,
    scheme: str,
    in_sample_dates: int,
    out_sample_dates: int,
    step_dates: int,
) -> list[tuple[int, int, int, int]]:
    """Walk-forward windows over the position of distinct calendar dates.

    Returns ``(train_lo, train_hi, test_lo, test_hi)`` half-open positions into the
    sorted distinct-date list, mirroring the index splitter's anchored/rolling logic.
    """
    if scheme not in _SCHEMES:
        raise ValueError(f"scheme must be one of {_SCHEMES}, got {scheme!r}.")
    n = len(dates)
    windows: list[tuple[int, int, int, int]] = []
    train_hi = in_sample_dates
    while train_hi < n:
        train_lo = 0 if scheme == "anchored" else train_hi - in_sample_dates
        test_lo = train_hi
        test_hi = min(train_hi + out_sample_dates, n)
        windows.append((train_lo, train_hi, test_lo, test_hi))
        train_hi += step_dates
    return windows


def _purge_embargo(
    decision_ts: pd.Series,
    label_end_ts: pd.Series,
    train_mask: np.ndarray,
    *,
    test_start: pd.Timestamp,
    distinct_dates: list[pd.Timestamp],
    embargo: int,
) -> tuple[np.ndarray, int, int]:
    """Apply purge + embargo to a boolean training mask. Returns (kept positions, n_purged, n_embargoed).

    Purge: drop a training row whose label horizon (``label_end_ts``) reaches into or
    past the held-out window (``label_end_ts >= test_start``) — its forward label was
    computed from prices inside the test period.

    Embargo: additionally drop training rows in the last ``embargo`` distinct dates
    before ``test_start``. With ``embargo >= horizon`` this is belt-and-suspenders
    over the purge (plan §6), kept explicit so the gap is auditable.
    """
    train_positions = np.flatnonzero(train_mask)
    n_raw = int(train_positions.size)
    if n_raw == 0:
        return train_positions, 0, 0

    le = label_end_ts.to_numpy()[train_positions]
    purge_keep = le < np.datetime64(test_start)
    n_purged = int((~purge_keep).sum())

    # Embargo cutoff: the date `embargo` distinct dates before the test window start.
    before = [d for d in distinct_dates if d < test_start]
    if embargo > 0 and before:
        cutoff = before[-embargo] if len(before) >= embargo else before[0]
        dt = decision_ts.to_numpy()[train_positions]
        embargo_keep = dt < np.datetime64(cutoff)
    else:
        embargo_keep = np.ones(n_raw, dtype=bool)

    keep = purge_keep & embargo_keep
    n_embargoed = int((purge_keep & ~embargo_keep).sum())
    return train_positions[keep], n_purged, n_embargoed


def generate_purged_splits(
    panel: pd.DataFrame,
    *,
    horizon: int,
    embargo: int | None = None,
    scheme: str = "anchored",
    in_sample_dates: int = 504,
    out_sample_dates: int = 126,
    step_dates: int = 126,
    decision_col: str = "decision_ts",
    label_end_col: str = "label_end_ts",
) -> list[PurgedSplit]:
    """Calendar-global, purged-and-embargoed walk-forward splits over a pooled panel.

    The boundary is a single calendar date applied to every pooled symbol at once.
    Training rows whose ``label_end`` overlaps the held-out window are purged and an
    ``embargo`` (defaulting to ``horizon``) distinct-date gap is removed before each
    test window. Returns one ``PurgedSplit`` per window; windows that leave no usable
    training row after purge/embargo are skipped. An empty panel yields ``[]``.
    """
    if embargo is None:
        embargo = horizon
    if panel.empty:
        return []

    decision_ts = panel[decision_col]
    label_end_ts = panel[label_end_col]
    distinct_dates = sorted(pd.to_datetime(decision_ts).unique())
    distinct_dates = [pd.Timestamp(d) for d in distinct_dates]

    windows = _date_windows(
        distinct_dates,
        scheme=scheme,
        in_sample_dates=in_sample_dates,
        out_sample_dates=out_sample_dates,
        step_dates=step_dates,
    )

    decision_np = decision_ts.to_numpy()
    splits: list[PurgedSplit] = []
    for train_lo, train_hi, test_lo, test_hi in windows:
        train_dates = distinct_dates[train_lo:train_hi]
        test_dates = distinct_dates[test_lo:test_hi]
        if not train_dates or not test_dates:
            continue
        test_start = test_dates[0]
        test_end = test_dates[-1]

        lo = np.datetime64(train_dates[0])
        hi = np.datetime64(train_dates[-1])
        train_mask = (decision_np >= lo) & (decision_np <= hi)
        test_lo_dt = np.datetime64(test_start)
        test_hi_dt = np.datetime64(test_end)
        test_mask = (decision_np >= test_lo_dt) & (decision_np <= test_hi_dt)

        kept_train, n_purged, n_embargoed = _purge_embargo(
            decision_ts,
            label_end_ts,
            train_mask,
            test_start=test_start,
            distinct_dates=distinct_dates,
            embargo=embargo,
        )
        if kept_train.size == 0:
            continue

        splits.append(
            PurgedSplit(
                train_idx=kept_train,
                test_idx=np.flatnonzero(test_mask),
                test_start=test_start,
                test_end=test_end,
                n_train_raw=int(train_mask.sum()),
                n_purged=n_purged,
                n_embargoed=n_embargoed,
            )
        )
    return splits


def inner_validation_split(
    panel: pd.DataFrame,
    train_idx: np.ndarray,
    *,
    horizon: int,
    embargo: int | None = None,
    val_fraction: float = 0.3,
    decision_col: str = "decision_ts",
    label_end_col: str = "label_end_ts",
) -> tuple[np.ndarray, np.ndarray]:
    """Split an outer training set into inner train/validation with the same discipline.

    The most recent ``val_fraction`` of distinct training dates becomes the validation
    fold (early stopping, calibration, threshold selection); the earlier dates are the
    inner training fold, **purged and embargoed** against the validation window exactly
    like the outer split. Returns ``(inner_train_idx, val_idx)`` as positional indices
    into the full panel. Raises ``ValueError`` if ``val_fraction`` is out of (0, 1).
    """
    if not 0.0 < val_fraction < 1.0:
        raise ValueError(f"val_fraction must be in (0, 1), got {val_fraction}.")
    if embargo is None:
        embargo = horizon

    train_idx = np.asarray(train_idx)
    if train_idx.size == 0:
        return train_idx, train_idx

    decision_ts = panel[decision_col]
    label_end_ts = panel[label_end_col]
    train_dates = sorted(pd.to_datetime(decision_ts.to_numpy()[train_idx]).unique())
    train_dates = [pd.Timestamp(d) for d in train_dates]
    n_dates = len(train_dates)
    n_val = max(1, int(round(n_dates * val_fraction)))
    if n_val >= n_dates:
        n_val = n_dates - 1
    if n_val < 1:
        return train_idx, np.empty(0, dtype=train_idx.dtype)

    val_start = train_dates[n_dates - n_val]
    decision_np = decision_ts.to_numpy()

    in_train = np.zeros(len(panel), dtype=bool)
    in_train[train_idx] = True
    val_mask = in_train & (decision_np >= np.datetime64(val_start))
    inner_train_mask = in_train & (decision_np < np.datetime64(val_start))

    kept_inner, _, _ = _purge_embargo(
        decision_ts,
        label_end_ts,
        inner_train_mask,
        test_start=val_start,
        distinct_dates=train_dates,
        embargo=embargo,
    )
    return kept_inner, np.flatnonzero(val_mask)
