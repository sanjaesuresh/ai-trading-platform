"""Walk-forward split generation: no overlap, no look-ahead, tail coverage."""

from __future__ import annotations

import pytest

from app.evaluation.walk_forward import generate_splits


def test_no_train_test_overlap() -> None:
    for scheme in ("anchored", "rolling"):
        for s in generate_splits(1000, scheme=scheme):
            assert s.test_start >= s.train_end


def test_test_strictly_after_train() -> None:
    # Every test index is strictly later than every train index — pins no look-ahead.
    for scheme in ("anchored", "rolling"):
        for s in generate_splits(1000, scheme=scheme):
            # train indices are [train_start, train_end); test [test_start, test_end)
            assert s.test_start >= s.train_end
            assert s.train_start < s.train_end < s.test_end


def test_anchored_train_start_is_zero() -> None:
    splits = generate_splits(1000, scheme="anchored")
    assert splits
    assert all(s.train_start == 0 for s in splits)
    train_ends = [s.train_end for s in splits]
    assert train_ends == sorted(train_ends)
    assert len(set(train_ends)) == len(train_ends)  # strictly increasing


def test_rolling_train_window_is_fixed_length() -> None:
    in_sample = 504
    for s in generate_splits(1000, scheme="rolling", in_sample_size=in_sample):
        assert s.train_end - s.train_start == in_sample


def test_split_count_for_known_size() -> None:
    splits = generate_splits(1000, in_sample_size=504, out_sample_size=126, step=126)
    assert len(splits) == 4
    first = splits[0]
    assert (first.train_start, first.train_end, first.test_start, first.test_end) == (
        0, 504, 504, 630,
    )
    last = splits[-1]
    assert (last.train_start, last.train_end, last.test_start, last.test_end) == (
        0, 882, 882, 1000,
    )


def test_tail_partial_oos_included() -> None:
    splits = generate_splits(1000, in_sample_size=504, out_sample_size=126, step=126)
    assert splits[-1].test_end == 1000


def test_too_few_bars_returns_empty() -> None:
    assert generate_splits(504, in_sample_size=504) == []
    assert generate_splits(300, in_sample_size=504) == []


def test_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError):
        generate_splits(1000, scheme="sideways")
