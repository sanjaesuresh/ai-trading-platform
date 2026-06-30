"""Point-in-time feature and label construction for the ML strategy (M1).

This module turns a Phase 2 *featured* frame (OHLCV plus the technical indicators
from ``app.data.feature_engineering``) into a model-ready matrix. Two halves, both
designed so future information cannot enter:

- **Causal features.** Scale-stable, point-in-time transforms (ratios, trailing
  returns, and trailing realized vol, not raw price levels) computed from per-symbol
  trailing windows only.
  A feature at bar ``N`` depends on no data after ``N``'s close — the decision time.
  Nothing is fit over the whole series or across the pooled panel, so pooling cannot
  introduce a full-series or cross-symbol leak.

- **Execution-matched fixed-horizon label.** Execution is next-bar-open: a signal
  from bar ``N``'s close fills at ``N+1``'s open. The label is therefore the sign of
  the **open[N+1] -> open[N+1+H]** return — the prices the trade actually earns — with
  a small neutral deadband so the model is not trained on coin-flip noise. The last
  ``H+1`` rows of each symbol are unlabelable and dropped honestly, never filled.

The builder never mutates its input (mirroring the indicator contract) and reports
how many rows survived warm-up, tail-drop, and the deadband, so a too-short dataset
is visible rather than silently producing a model trained on almost nothing.

Overlapping ``H``-day labels share calendar time, so consecutive samples are not
independent. ``compute_uniqueness_weights`` returns Lopez de Prado concurrency
weights (and the effective sample size) so training and the §8 significance math do
not over-count redundant information.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.data.feature_engineering import INDICATOR_COLUMNS

# Bump when the feature definitions below change in any way that would make an
# old model's inputs mean something different. The registry pins this string and
# the strategy refuses to run a model whose stored version does not match.
FEATURE_SPEC_VERSION = "v1"

# Causal feature columns this module produces, in order. Every one is computable
# from bars known at or before the decision bar's close, from per-symbol trailing
# windows only. Kept deliberately lean (plan 3.2).
FEATURE_COLUMNS: tuple[str, ...] = (
    "f_close_over_sma20",
    "f_close_over_sma50",
    "f_sma20_over_sma50",
    "f_close_over_ema20",
    "f_rsi_14",
    "f_macd_over_close",
    "f_macd_hist_over_close",
    "f_vol_over_volma20",
    "f_ret_5",
    "f_ret_10",
    "f_realized_vol_20",
)

# Indicator columns the feature builder consumes (a subset of what
# add_technical_indicators produces). Linked to the data layer's authoritative list
# so a rename there fails loudly at import time rather than silently at runtime.
_REQUIRED_INDICATORS = (
    "sma_20",
    "sma_50",
    "ema_20",
    "rsi_14",
    "macd",
    "macd_signal",
    "volume_ma_20",
)
_missing_indicators = [c for c in _REQUIRED_INDICATORS if c not in INDICATOR_COLUMNS]
if _missing_indicators:  # pragma: no cover - guards against an upstream rename
    raise ImportError(
        "ml.features expects indicator column(s) not produced by "
        f"add_technical_indicators: {', '.join(_missing_indicators)}."
    )
_REQUIRED_PRICE_COLUMNS = ("timestamp", "open", "close", "volume")

DEFAULT_HORIZON = 5
# Default deadband is zero (pure open-to-open sign). The deadband is a tuned knob
# enumerated in the deflated-Sharpe configuration count (plan §8); callers set a
# small positive band to drop coin-flip rows.
DEFAULT_DEADBAND = 0.0

# Panel column names (the pooled model-ready matrix).
COL_SYMBOL = "symbol"
COL_DECISION_TS = "decision_ts"
COL_LABEL_START_TS = "label_start_ts"
COL_LABEL_END_TS = "label_end_ts"
COL_LABEL = "label"
COL_WEIGHT = "weight"


@dataclass(frozen=True)
class FeatureLabelSpec:
    """The exact feature/label definition a model was trained under.

    Stored in the model registry; the strategy asserts the live spec matches the
    model's recorded one before running, so a silent feature drift cannot feed the
    model garbage with full confidence.
    """

    version: str = FEATURE_SPEC_VERSION
    feature_columns: tuple[str, ...] = FEATURE_COLUMNS
    horizon: int = DEFAULT_HORIZON
    deadband: float = DEFAULT_DEADBAND


@dataclass(frozen=True)
class BuildReport:
    """Honest row accounting for one symbol's matrix build."""

    symbol: str
    rows_input: int
    rows_feature_valid: int
    rows_labelable: int
    rows_final: int
    dropped_warmup: int
    dropped_tail_unlabelable: int
    dropped_neutral: int


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a new frame with the causal feature columns appended. Input untouched.

    Requires the Phase 2 indicator columns and OHLCV. Every feature is a
    point-in-time, scale-stable transform of data at or before each bar's close.
    """
    missing = [
        c
        for c in (*_REQUIRED_PRICE_COLUMNS, *_REQUIRED_INDICATORS)
        if c not in frame.columns
    ]
    if missing:
        raise ValueError(f"Featured frame missing column(s): {', '.join(missing)}.")

    out = frame.copy()
    close = out["close"]

    out["f_close_over_sma20"] = close / out["sma_20"] - 1.0
    out["f_close_over_sma50"] = close / out["sma_50"] - 1.0
    out["f_sma20_over_sma50"] = out["sma_20"] / out["sma_50"] - 1.0
    out["f_close_over_ema20"] = close / out["ema_20"] - 1.0
    out["f_rsi_14"] = out["rsi_14"] / 100.0
    out["f_macd_over_close"] = out["macd"] / close
    out["f_macd_hist_over_close"] = (out["macd"] - out["macd_signal"]) / close
    out["f_vol_over_volma20"] = out["volume"] / out["volume_ma_20"] - 1.0
    out["f_ret_5"] = close / close.shift(5) - 1.0
    out["f_ret_10"] = close / close.shift(10) - 1.0
    # Trailing realized vol of daily returns (per-symbol, trailing only).
    daily_ret = close.pct_change()
    out["f_realized_vol_20"] = daily_ret.rolling(window=20, min_periods=20).std()

    return out


def build_labels(
    frame: pd.DataFrame,
    *,
    horizon: int = DEFAULT_HORIZON,
    deadband: float = DEFAULT_DEADBAND,
) -> pd.DataFrame:
    """Return a frame of label columns aligned to ``frame``'s index. Input untouched.

    The label for bar ``N`` is the sign of the **open[N+1] -> open[N+1+H]** return
    (the executable, next-bar-open anchor), with a neutral deadband:

    - ``1.0`` if the forward return ``> deadband`` (up),
    - ``0.0`` if the forward return ``< -deadband`` (down),
    - ``NaN`` if ``|forward return| <= deadband`` (neutral) or the row is unlabelable
      (the final ``H+1`` rows, whose exit open does not exist).

    Columns: ``label`` (float, with NaN), ``label_start_ts`` (= timestamp[N+1]),
    ``label_end_ts`` (= timestamp[N+1+H]). The ``_ts`` columns carry the holding
    interval the purge/embargo splitter needs.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}.")
    if deadband < 0.0:
        raise ValueError(f"deadband must be >= 0, got {deadband}.")

    open_px = frame["open"]
    ts = frame["timestamp"]

    open_entry = open_px.shift(-1)  # open[N+1]
    open_exit = open_px.shift(-(1 + horizon))  # open[N+1+H]
    forward_return = open_exit / open_entry - 1.0

    label = pd.Series(np.nan, index=frame.index, dtype="float64")
    label = label.where(~(forward_return > deadband), 1.0)
    label = label.where(~(forward_return < -deadband), 0.0)
    # Rows with NaN forward_return (unlabelable tail) stay NaN by construction.

    return pd.DataFrame(
        {
            COL_LABEL: label,
            COL_LABEL_START_TS: ts.shift(-1),
            COL_LABEL_END_TS: ts.shift(-(1 + horizon)),
        }
    )


def _concurrency(entry_pos: np.ndarray, exit_pos: np.ndarray, span_end: int) -> np.ndarray:
    """Concurrency per bar: how many holding intervals cover each bar position.

    Difference array + prefix sum, O(n + span). ``span_end`` is the last bar position
    any interval can touch.
    """
    delta = np.zeros(span_end + 2, dtype="float64")
    np.add.at(delta, entry_pos, 1.0)
    np.add.at(delta, exit_pos + 1, -1.0)
    return np.cumsum(delta)


def _average_uniqueness(
    entry_pos: np.ndarray, exit_pos: np.ndarray, concurrency: np.ndarray
) -> np.ndarray:
    """Mean ``1 / concurrency`` over each label's holding interval (Lopez de Prado).

    Concurrency is supplied (counted over the full set of overlapping labels), so a
    kept label's uniqueness reflects overlap with *all* concurrent labels — including
    deadband-neutral neighbours it would otherwise look spuriously independent from.
    """
    weights = np.empty(len(entry_pos), dtype="float64")
    for i in range(len(entry_pos)):
        a = int(entry_pos[i])
        b = int(exit_pos[i])
        weights[i] = float(np.mean(1.0 / concurrency[a : b + 1]))
    return weights


def _uniqueness_weights(
    entry_pos: np.ndarray, exit_pos: np.ndarray
) -> np.ndarray:
    """Average-uniqueness weights with concurrency counted over the given intervals.

    ``entry_pos``/``exit_pos`` are inclusive integer bar positions of each label's
    holding interval (within one symbol). Returns one weight per label in input order;
    an empty input returns an empty array.
    """
    n = len(entry_pos)
    if n == 0:
        return np.empty(0, dtype="float64")
    concurrency = _concurrency(entry_pos, exit_pos, int(exit_pos.max()))
    return _average_uniqueness(entry_pos, exit_pos, concurrency)


def build_symbol_panel(
    frame: pd.DataFrame,
    *,
    symbol: str,
    spec: FeatureLabelSpec | None = None,
) -> tuple[pd.DataFrame, BuildReport]:
    """Build one symbol's model-ready matrix plus an honest row-count report.

    ``frame`` is that symbol's featured frame (OHLCV + indicators), sorted ascending
    by timestamp. Returns a panel with one row per usable decision bar: the symbol,
    the decision timestamp, the label's holding-interval timestamps, the feature
    columns, the 0/1 label, and the uniqueness weight. Rows are kept only when every
    feature is defined (past warm-up), the row is labelable (not in the tail), and the
    label is non-neutral (outside the deadband).
    """
    spec = spec or FeatureLabelSpec()
    rows_input = int(len(frame))

    featured = build_features(frame).reset_index(drop=True)
    labels = build_labels(
        featured, horizon=spec.horizon, deadband=spec.deadband
    ).reset_index(drop=True)

    feature_valid = featured[list(spec.feature_columns)].notna().all(axis=1)
    labelable = labels[COL_LABEL_END_TS].notna()
    non_neutral = labels[COL_LABEL].notna()

    keep = feature_valid & labelable & non_neutral

    # Uniqueness weighting. Concurrency is counted over *all* labelable holding
    # intervals (a deadband-neutral neighbour still consumes calendar time and makes
    # its kept neighbours less independent), but a weight is returned only for kept
    # rows. Holding interval for bar N is positions [N+1, N+1+H].
    pos = np.arange(len(featured))
    all_entry = pos[labelable.to_numpy()] + 1
    all_exit = all_entry + spec.horizon
    keep_entry = pos[keep.to_numpy()] + 1
    keep_exit = keep_entry + spec.horizon
    if keep_entry.size:
        concurrency = _concurrency(all_entry, all_exit, int(all_exit.max()))
        weights = _average_uniqueness(keep_entry, keep_exit, concurrency)
    else:
        weights = np.empty(0, dtype="float64")

    panel = pd.DataFrame(
        {
            COL_SYMBOL: symbol,
            COL_DECISION_TS: featured.loc[keep, "timestamp"].to_numpy(),
            COL_LABEL_START_TS: labels.loc[keep, COL_LABEL_START_TS].to_numpy(),
            COL_LABEL_END_TS: labels.loc[keep, COL_LABEL_END_TS].to_numpy(),
            COL_LABEL: labels.loc[keep, COL_LABEL].to_numpy(),
            COL_WEIGHT: weights,
        }
    )
    for col in spec.feature_columns:
        panel[col] = featured.loc[keep, col].to_numpy()
    panel = panel.reset_index(drop=True)

    report = BuildReport(
        symbol=symbol,
        rows_input=rows_input,
        rows_feature_valid=int(feature_valid.sum()),
        rows_labelable=int(labelable.sum()),
        rows_final=int(keep.sum()),
        dropped_warmup=int((~feature_valid).sum()),
        dropped_tail_unlabelable=int((~labelable).sum()),
        dropped_neutral=int((feature_valid & labelable & ~non_neutral).sum()),
    )
    return panel, report


def build_pooled_panel(
    frames: dict[str, pd.DataFrame],
    *,
    spec: FeatureLabelSpec | None = None,
) -> tuple[pd.DataFrame, list[BuildReport]]:
    """Pool per-symbol panels into one matrix, sorted by decision timestamp.

    Weights are computed per symbol (each symbol is its own price timeline) before
    pooling. The pooled panel carries a fresh ``RangeIndex`` so positional indices
    from the splitter address it directly. The calendar-global splitter keys on
    ``decision_ts``; symbols are interleaved in time, not concatenated end to end.

    Known limitation: uniqueness is corrected for temporal overlap *within* a symbol
    only. Cross-sectional correlation across pooled symbols on the same dates still
    inflates the effective sample size; the deflated-Sharpe treatment (plan §8, M3)
    is where that residual is accounted for, not here.
    """
    spec = spec or FeatureLabelSpec()
    panels: list[pd.DataFrame] = []
    reports: list[BuildReport] = []
    for symbol in sorted(frames):
        panel, report = build_symbol_panel(frames[symbol], symbol=symbol, spec=spec)
        panels.append(panel)
        reports.append(report)

    columns = [
        COL_SYMBOL,
        COL_DECISION_TS,
        COL_LABEL_START_TS,
        COL_LABEL_END_TS,
        COL_LABEL,
        COL_WEIGHT,
        *spec.feature_columns,
    ]
    if not panels or all(p.empty for p in panels):
        return pd.DataFrame(columns=columns), reports

    pooled = pd.concat(panels, ignore_index=True)
    # Stable sort keeps per-symbol order within a date deterministic.
    pooled = pooled.sort_values(
        COL_DECISION_TS, kind="stable"
    ).reset_index(drop=True)
    return pooled[columns], reports


def compute_uniqueness_weights(
    entry_pos: np.ndarray, exit_pos: np.ndarray
) -> np.ndarray:
    """Public wrapper over the concurrency weighting (for tests and the trainer)."""
    return _uniqueness_weights(np.asarray(entry_pos), np.asarray(exit_pos))


def effective_sample_size(weights: pd.Series | np.ndarray) -> float:
    """Effective number of independent samples = sum of uniqueness weights (LdP).

    Feeds the deflated-Sharpe track length T (plan §8): overlapping labels mean the
    raw row count overstates how much independent information the data carries.
    """
    arr = np.asarray(weights, dtype="float64")
    return float(arr.sum())
