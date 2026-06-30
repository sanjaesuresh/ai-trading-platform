"""LLM annotation layer (Phase 5 M3).

Wraps the Claude client to turn one news item into a structured annotation
(sentiment, event type, relevance, rationale). Built for honest cost control:
Batch API at half price, content-hash caching so an unchanged article is never
re-billed, structured outputs for schema-validated fields, prompt caching on the
shared rubric, a no-network stub for tests/CI, and token-metered billed-cost
capture so the ablation's cost charge is real spend, not an estimate.

The ``anthropic`` SDK is imported lazily inside the real client only, so this
package (schema, prompt, cost, cache, stub) imports and tests with no SDK and no
key.
"""
