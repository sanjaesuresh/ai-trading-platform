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
