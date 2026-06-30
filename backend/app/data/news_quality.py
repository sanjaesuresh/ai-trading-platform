"""News data-quality gate (Phase 5 M2).

Unlike the OHLCV gate — which aborts the whole batch on any blocking error —
news quality is mostly a *cleaning* gate: a feed routinely carries a few
unusable items (a null timestamp, a duplicate, an item for a symbol we don't
trade) that should be dropped without failing the run, because sparse and messy
coverage is normal for news.

So this returns a *cleaned* frame plus a report. Only a structural problem
(missing contract columns) is blocking; per-item problems drop the item and bump
``items_dropped``. An empty input is valid (a symbol may simply have no news in
the window), not an error.

The discipline (plan §3): deduplicate items, reject implausible timestamps,
normalize/validate symbol attribution, and drop items that can't be pinned to a
tradable symbol and a point in time.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from app.data.news_providers.base import NEWS_COLUMNS, NEWS_REQUIRED_COLUMNS

# Timestamps outside this window are implausible for tradable-symbol news.
_EPOCH_FLOOR = pd.Timestamp("1990-01-01", tz="UTC")
# Allow a small clock-skew tolerance for "future" publish times.
_FUTURE_SKEW = pd.Timedelta(days=2)


@dataclass
class NewsQualityReport:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    items_in: int = 0
    items_kept: int = 0
    items_dropped: int = 0


def check_and_clean_news(
    frame: pd.DataFrame,
    *,
    valid_symbols: Iterable[str] | None = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, NewsQualityReport]:
    """Validate structure and clean per-item problems from a news frame.

    Parameters
    ----------
    frame:
        Provider output in the ``NEWS_COLUMNS`` shape.
    valid_symbols:
        If given, items whose ``symbol`` is not in this set are dropped — they
        can't be attributed to a tradable instrument.
    now:
        Reference "now" for the future-timestamp check (injectable for tests);
        defaults to the current UTC time.

    Returns ``(clean_frame, report)``. ``clean_frame`` is a new frame (input not
    mutated) with the same ``NEWS_COLUMNS`` and a fresh RangeIndex. A blocking
    structural error returns an empty frame with ``passed=False``.
    """
    now_ts = pd.Timestamp(now or datetime.now(UTC))
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    future_cutoff = now_ts + _FUTURE_SKEW

    missing = [c for c in NEWS_COLUMNS if c not in frame.columns]
    if missing:
        return (
            _empty_like(),
            NewsQualityReport(
                passed=False,
                errors=[f"Missing required column(s): {', '.join(missing)}."],
                items_in=int(len(frame)),
            ),
        )

    items_in = int(len(frame))
    if items_in == 0:
        # An empty news window is valid, not a failure.
        return _empty_like(), NewsQualityReport(passed=True, items_in=0)

    work = frame.copy().reset_index(drop=True)
    warnings: list[str] = []

    # 1. Drop rows with a null in any required column.
    null_mask = work[NEWS_REQUIRED_COLUMNS].isna().any(axis=1)
    if null_mask.any():
        warnings.append(f"Dropped {int(null_mask.sum())} item(s) with null required field(s).")
    work = work.loc[~null_mask]

    # 2. Reject implausible timestamps (either timestamp out of bounds).
    pub = pd.to_datetime(work["published_at"], utc=True)
    seen = pd.to_datetime(work["first_seen_at"], utc=True)
    bad_time = (
        (pub < _EPOCH_FLOOR)
        | (pub > future_cutoff)
        | (seen < _EPOCH_FLOOR)
        | (seen > future_cutoff)
    )
    if bad_time.any():
        warnings.append(f"Dropped {int(bad_time.sum())} item(s) with implausible timestamp(s).")
    work = work.loc[~bad_time]

    # 3. Drop items not attributable to a tradable symbol.
    if valid_symbols is not None:
        allowed = {s.upper() for s in valid_symbols}
        sym_ok = work["symbol"].str.upper().isin(allowed)
        if (~sym_ok).any():
            warnings.append(
                f"Dropped {int((~sym_ok).sum())} item(s) for untradable symbol(s)."
            )
        work = work.loc[sym_ok]

    # 4. Deduplicate on (symbol, item_id, headline, body) — same content is the
    #    same availability event; a revised body (different text) is kept as a new
    #    item, matching the storage key in M2.
    before = len(work)
    work = work.drop_duplicates(subset=["symbol", "item_id", "headline", "body"], keep="first")
    deduped = before - len(work)
    if deduped:
        warnings.append(f"Dropped {deduped} duplicate item(s).")

    clean = work.sort_values("published_at").reset_index(drop=True)[NEWS_COLUMNS]
    items_kept = int(len(clean))
    report = NewsQualityReport(
        passed=True,
        warnings=warnings,
        items_in=items_in,
        items_kept=items_kept,
        items_dropped=items_in - items_kept,
    )
    return clean, report


def _empty_like() -> pd.DataFrame:
    from app.data.news_providers.base import empty_news_frame

    return empty_news_frame()
