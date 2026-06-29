"""Fees are a basis-point fraction of absolute notional."""

from __future__ import annotations

import pytest

from app.backtesting.fees import calculate_fee


def test_fee_is_bps_of_notional() -> None:
    # 5 bps of 10,000 = 5.0.
    assert calculate_fee(10_000.0, 5) == pytest.approx(5.0)


def test_fee_uses_absolute_notional() -> None:
    assert calculate_fee(-10_000.0, 5) == pytest.approx(5.0)


def test_zero_bps_is_free() -> None:
    assert calculate_fee(10_000.0, 0) == 0.0
