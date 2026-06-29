"""Slippage moves the fill against the trader: buys up, sells down."""

from __future__ import annotations

import pytest

from app.backtesting.slippage import apply_slippage


def test_buy_slippage_fills_above_price() -> None:
    assert apply_slippage(100.0, "BUY", 10) == pytest.approx(100.0 * 1.001)


def test_sell_slippage_fills_below_price() -> None:
    assert apply_slippage(100.0, "SELL", 10) == pytest.approx(100.0 * 0.999)


def test_side_is_case_insensitive() -> None:
    assert apply_slippage(100.0, "buy", 10) == pytest.approx(100.0 * 1.001)


def test_zero_bps_is_a_no_op() -> None:
    assert apply_slippage(100.0, "BUY", 0) == 100.0
    assert apply_slippage(100.0, "SELL", 0) == 100.0


def test_unknown_side_raises() -> None:
    with pytest.raises(ValueError, match="Unknown trade side"):
        apply_slippage(100.0, "SHORT", 10)
