"""Token-metered, tier-aware annotation cost (Phase 5 M3/§5).

Cost is the actual billed amount derived from the API's real per-call token
usage, never count × flat rate. It is tier-aware (a Haiku→Sonnet escalation is
charged at its real rate) and summed over **every billed article** — including
low-relevance and failed annotations that are billed but later dropped from
features — so the relevance cutoff cannot launder cost off the books.

Pricing verified against the claude-api reference at M3 (2026-06-30):
Haiku 4.5 standard $1.00 / $5.00 per MTok input/output; Batch API = 50% off all
token usage; cache read = 0.1× base input; cache write (5-minute TTL) = 1.25×
base input. Re-verify on any pricing change — these are config, not magic numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

_PER_MTOK = 1_000_000.0
# Batch API is half price on all token usage.
BATCH_MULTIPLIER = 0.5


@dataclass(frozen=True)
class TokenUsage:
    """Real token usage for one annotation call (from the API or the stub)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class ModelPricing:
    """Per-MTok USD rates for a model tier (standard, pre-batch-discount)."""

    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float


# Standard (non-batch) per-MTok rates. Batch is applied as BATCH_MULTIPLIER.
PRICING: dict[str, ModelPricing] = {
    "claude-haiku-4-5": ModelPricing(1.00, 5.00, 0.10, 1.25),
    "claude-haiku-4-5-20251001": ModelPricing(1.00, 5.00, 0.10, 1.25),
    "claude-sonnet-4-6": ModelPricing(3.00, 15.00, 0.30, 3.75),
}


class UnknownModelPricingError(KeyError):
    """No pricing entry for a model id — refuse to guess a cost."""


def annotation_cost(usage: TokenUsage, model_id: str, *, batch: bool) -> float:
    """Return the billed USD cost of one annotation call.

    Tier-aware (rates keyed by ``model_id``) and batch-aware (half price when
    ``batch``). Raises ``UnknownModelPricingError`` rather than silently
    under-charging an unpriced model.
    """
    pricing = PRICING.get(model_id)
    if pricing is None:
        raise UnknownModelPricingError(
            f"No pricing for model '{model_id}'; add it to PRICING before billing."
        )
    multiplier = BATCH_MULTIPLIER if batch else 1.0
    raw = (
        usage.input_tokens * pricing.input_per_mtok
        + usage.output_tokens * pricing.output_per_mtok
        + usage.cache_read_tokens * pricing.cache_read_per_mtok
        + usage.cache_write_tokens * pricing.cache_write_per_mtok
    )
    return raw / _PER_MTOK * multiplier
