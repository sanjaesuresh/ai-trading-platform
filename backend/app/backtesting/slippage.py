"""Slippage model: the effective fill price moves against the trader."""

from __future__ import annotations


def apply_slippage(price: float, side: str, slippage_bps: float) -> float:
    """Return the effective fill price after slippage.

    A buy fills higher than quoted, a sell fills lower, by ``slippage_bps``.
    """
    factor = slippage_bps / 10_000.0
    normalized = side.upper()
    if normalized == "BUY":
        return price * (1.0 + factor)
    if normalized == "SELL":
        return price * (1.0 - factor)
    raise ValueError(f"Unknown trade side: {side!r}")
