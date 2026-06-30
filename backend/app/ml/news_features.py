"""Point-in-time news feature builder — the Phase 5 keystone (M4 / §2).

This is the part most able to fool us, so it is built and reviewed first, exactly
as Phase 4 treated purge/embargo. Given a symbol's featured frame and that
symbol's annotated articles, it returns new per-symbol, per-day, point-in-time
news columns. The discipline (§2):

- **Availability time = max(publish, first_seen).** A revised or back-dated
  article re-annotates under a new content hash and is stored at its own
  first-seen; here it becomes available only at that first-seen instant, never
  back-dated onto the original publish bar.
- **DST-correct UTC comparison.** Bar timestamps are tz-naive daily dates with no
  intraday close; news timestamps are tz-aware UTC. Comparing naively is an
  after-close-into-same-day leak. The builder derives each bar's close from the
  **actual exchange session close in exchange-local time** (DST-correct) and
  compares in UTC. The Phase 1-4 loader is left tz-naive on purpose — the
  normalization lives here, at the one place the two clocks meet.
- **Cutoff with a ≥1-bar embargo.** The feature on the row whose signal fills at
  bar N+1's open may use only items whose availability time is at or before bar
  N's close, minus a safety embargo of at least one bar. So row i uses items
  available at or before the session close of bar ``i - embargo``.
- **Trailing, causal, per-row only.** Every column is a rolling/decay/flag over
  trailing arrivals — never a full-series or fit-on-train transform the splitter
  cannot catch. Non-mutating, like ``add_technical_indicators``.
- **Never NaN.** The Phase 4 panel keep-mask drops any row with a NaN feature, so
  every news column — including the division-bearing z-score and ratio columns —
  has a defined value on quiet days (neutral 0) and before the first article, so a
  partially-newsy symbol's quiet interior is never dropped. All warm-up windows
  are ≤ the price warm-up (50 bars), so news adds no extra head-drop.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Bump when any news-feature computation below changes meaning (§3/M5 gates on it).
NEWS_FEATURE_SPEC_VERSION = "v1"

# News feature columns, in order. All causal, all defined on quiet days.
NEWS_FEATURE_COLUMNS: tuple[str, ...] = (
    "n_has_news",  # arrival flag on this bar
    "n_days_since_news",  # saturating staleness in [0, 1] (1 = none yet / stale)
    "n_sent_decay",  # exponentially-decayed trailing sentiment
    "n_sent_mean_20",  # trailing mean sentiment (0 on a quiet window — not 0/0 NaN)
    "n_volume_z",  # trailing z-score of news volume (0 on zero-variance — not NaN)
    "n_event_flag",  # high-relevance event in the trailing window
)

# Defaults. Embargo is ≥ 1 bar per §2. Windows are ≤ the 50-bar price warm-up.
DEFAULT_NEWS_EMBARGO = 1
DEFAULT_DECAY_HALFLIFE = 5
DEFAULT_SENT_WINDOW = 20
DEFAULT_VOL_WINDOW = 20
DEFAULT_EVENT_WINDOW = 5
DEFAULT_DAYS_SINCE_CAP = 50
DEFAULT_EVENT_RELEVANCE = 0.5

_EXCHANGE_TZ = "America/New_York"
_SESSION_CLOSE = "16:00"

_ANNOTATION_COLUMNS = ("published_at", "first_seen_at", "sentiment", "relevance")


def session_close_utc(
    timestamps: pd.Series,
    *,
    exchange_tz: str = _EXCHANGE_TZ,
    close_time: str = _SESSION_CLOSE,
) -> pd.Series:
    """Map tz-naive daily bar dates to their tz-aware UTC session-close instants.

    DST-correct: the close is localized in exchange-local time, so the UTC instant
    moves with daylight saving rather than being pinned to a naive calendar date.
    """
    dates = pd.to_datetime(timestamps).dt.normalize()
    hours, minutes = (int(x) for x in close_time.split(":"))
    local = dates + pd.Timedelta(hours=hours, minutes=minutes)
    localized = local.dt.tz_localize(
        exchange_tz, nonexistent="shift_forward", ambiguous=False
    )
    return localized.dt.tz_convert("UTC")


def _to_utc_ns(values: pd.Series | np.ndarray) -> np.ndarray:
    """Convert a datetime-like sequence to int64 UTC nanoseconds since the epoch."""
    series = pd.to_datetime(pd.Series(list(values)), utc=True)
    return np.asarray(series.values, dtype="datetime64[ns]").astype("int64")


def _require_tz_aware(values: pd.Series, name: str) -> None:
    """Fail loud if *values* are tz-naive.

    The keystone cutoff only holds if news timestamps are unambiguous UTC instants.
    A tz-naive timestamp would be silently assumed UTC by ``_to_utc_ns`` — and a
    naive Eastern time read as UTC shifts ~4-5h, which could push after-close news
    into a same-day decision (a real leak from bad input). So refuse naive input
    rather than trust it.
    """
    parsed = pd.to_datetime(pd.Series(list(values)))
    if getattr(parsed.dt, "tz", None) is None:
        raise ValueError(
            f"{name} must be timezone-aware (the NewsProvider contract emits UTC); "
            "got naive timestamps."
        )


def build_news_features(
    frame: pd.DataFrame,
    annotations: pd.DataFrame | None,
    *,
    embargo: int = DEFAULT_NEWS_EMBARGO,
    relevance_threshold: float = 0.0,
    decay_halflife: int = DEFAULT_DECAY_HALFLIFE,
    sent_window: int = DEFAULT_SENT_WINDOW,
    vol_window: int = DEFAULT_VOL_WINDOW,
    event_window: int = DEFAULT_EVENT_WINDOW,
    days_since_cap: int = DEFAULT_DAYS_SINCE_CAP,
    event_relevance: float = DEFAULT_EVENT_RELEVANCE,
    exchange_tz: str = _EXCHANGE_TZ,
    close_time: str = _SESSION_CLOSE,
) -> pd.DataFrame:
    """Return a new frame with the ``n_*`` news columns appended. Input untouched.

    ``frame`` is the symbol's featured frame (must carry a tz-naive ``timestamp``).
    ``annotations`` is that symbol's article-level annotations with columns
    ``published_at``, ``first_seen_at`` (datetime-like), ``sentiment``, and
    ``relevance``; ``None`` or empty means no news (all columns take their quiet
    defaults). Output columns are never NaN.
    """
    if embargo < 1:
        raise ValueError(f"embargo must be >= 1 (a safety bar is required), got {embargo}.")
    if "timestamp" not in frame.columns:
        raise ValueError("News feature frame is missing the 'timestamp' column.")

    out = frame.copy()
    n = len(out)
    # The cutoff arithmetic assumes ascending bars (cutoffs must be monotonic for
    # searchsorted); refuse an out-of-order frame rather than mis-assign arrivals.
    if n > 1 and not pd.to_datetime(out["timestamp"]).is_monotonic_increasing:
        raise ValueError("News feature frame 'timestamp' must be ascending.")

    # Quiet / pre-first-article defaults (every column defined, never NaN).
    out["n_has_news"] = 0.0
    out["n_days_since_news"] = 1.0
    out["n_sent_decay"] = 0.0
    out["n_sent_mean_20"] = 0.0
    out["n_volume_z"] = 0.0
    out["n_event_flag"] = 0.0
    if n == 0:
        return out

    # Per-bar cutoff in UTC ns: row i may see news available at or before the
    # session close of bar i - embargo. Rows before that get a -inf cutoff (no news).
    closes_ns = _to_utc_ns(
        session_close_utc(out["timestamp"], exchange_tz=exchange_tz, close_time=close_time)
    )
    neg = np.iinfo(np.int64).min
    cutoffs = np.full(n, neg, dtype=np.int64)
    if n > embargo:
        cutoffs[embargo:] = closes_ns[: n - embargo]

    count = np.zeros(n, dtype="float64")
    sent_sum = np.zeros(n, dtype="float64")
    event_count = np.zeros(n, dtype="float64")

    if annotations is not None and len(annotations) > 0:
        missing = [c for c in _ANNOTATION_COLUMNS if c not in annotations.columns]
        if missing:
            raise ValueError(
                f"Annotations frame missing column(s): {', '.join(missing)}."
            )
        _require_tz_aware(annotations["published_at"], "published_at")
        _require_tz_aware(annotations["first_seen_at"], "first_seen_at")
        pub_ns = _to_utc_ns(annotations["published_at"])
        seen_ns = _to_utc_ns(annotations["first_seen_at"])
        # Availability time = max(publish, first_seen) (§2).
        avail_ns = np.maximum(pub_ns, seen_ns)
        sentiment = annotations["sentiment"].to_numpy(dtype="float64")
        relevance = annotations["relevance"].to_numpy(dtype="float64")

        keep = relevance >= relevance_threshold
        avail_ns, sentiment, relevance = avail_ns[keep], sentiment[keep], relevance[keep]

        # Arrival bar = first bar whose cutoff >= availability (cutoffs ascending).
        arrival = np.searchsorted(cutoffs, avail_ns, side="left")
        usable = arrival < n
        arrival, sentiment, relevance = arrival[usable], sentiment[usable], relevance[usable]

        if arrival.size:
            count = np.bincount(arrival, minlength=n).astype("float64")
            np.add.at(sent_sum, arrival, sentiment)
            event_arrival = arrival[relevance >= event_relevance]
            if event_arrival.size:
                event_count = np.bincount(event_arrival, minlength=n).astype("float64")

    out["n_has_news"] = (count > 0).astype("float64")
    out["n_days_since_news"] = _days_since(count, cap=days_since_cap)
    out["n_sent_decay"] = _decayed(sent_sum, halflife=decay_halflife)

    count_s = pd.Series(count)
    sent_s = pd.Series(sent_sum)
    sent_roll = sent_s.rolling(sent_window, min_periods=1).sum().to_numpy()
    cnt_roll = count_s.rolling(sent_window, min_periods=1).sum().to_numpy()
    # Trailing mean sentiment; a zero-news window is 0/0 → neutral 0, never NaN.
    safe_cnt = np.where(cnt_roll > 0, cnt_roll, 1.0)
    out["n_sent_mean_20"] = np.where(cnt_roll > 0, sent_roll / safe_cnt, 0.0)

    roll_mean = count_s.rolling(vol_window, min_periods=1).mean().to_numpy()
    roll_std = count_s.rolling(vol_window, min_periods=1).std(ddof=0).to_numpy()
    safe_std = np.where(roll_std > 0, roll_std, 1.0)
    out["n_volume_z"] = np.where(roll_std > 0, (count - roll_mean) / safe_std, 0.0)

    event_roll = pd.Series(event_count).rolling(event_window, min_periods=1).sum()
    out["n_event_flag"] = (event_roll.to_numpy() > 0).astype("float64")

    # Defensive: guarantee the keystone invariant — no news column is ever NaN.
    for col in NEWS_FEATURE_COLUMNS:
        out[col] = pd.Series(out[col].to_numpy(), index=out.index).fillna(0.0)
    return out


def _days_since(count: np.ndarray, *, cap: int) -> np.ndarray:
    """Saturating, normalized bars-since-last-arrival in [0, 1] (1 = stale/none)."""
    n = count.size
    out = np.empty(n, dtype="float64")
    last = -1
    for i in range(n):
        if count[i] > 0:
            last = i
        gap = cap if last < 0 else min(cap, i - last)
        out[i] = gap / cap
    return out


def _decayed(sent_sum: np.ndarray, *, halflife: int) -> np.ndarray:
    """Causal exponentially-decayed trailing sum of per-bar sentiment."""
    lam = 0.5 ** (1.0 / halflife)
    out = np.empty(sent_sum.size, dtype="float64")
    acc = 0.0
    for i in range(sent_sum.size):
        acc = acc * lam + sent_sum[i]
        out[i] = acc
    return out
