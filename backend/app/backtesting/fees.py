"""Trading fees, expressed in basis points of notional."""

from __future__ import annotations


def calculate_fee(notional: float, fee_bps: float) -> float:
    """Fee charged on a traded notional at a basis-point rate (1 bps = 0.01%)."""
    return abs(notional) * (fee_bps / 10_000.0)
