"""The classification prompt and its version (Phase 5 M3).

PROMPT_VERSION is part of the content-hash cache key and feeds the §6
multiple-testing trial count: each prompt revision busts the cache, re-bills, and
counts as another search trial. Bump it whenever the rubric below changes.

The system prompt is the shared, cacheable prefix. Prompt caching only engages
above Haiku 4.5's minimum cacheable prefix (4096 tokens, verified against the
claude-api reference at M3); the rubric below is unlikely to clear that alone, so
caching may be a no-op until the rubric grows — surfaced here rather than assumed,
per §5. The cost accounting never assumes cache pricing it hasn't verified.
"""

from __future__ import annotations

from app.llm.schema import EVENT_TAXONOMY

# Bump on any change to the rubric/taxonomy/output contract below.
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = f"""You are a financial-news classifier for a simulated trading \
research platform. You read one news item about one publicly traded company and \
return a structured annotation. You never give investment advice and never \
predict prices; you only describe the text in front of you.

Return exactly these fields:

- sentiment: a number in [-1, 1]. The sign is the polarity toward the company \
(negative = bad for the company, positive = good), and the magnitude is the \
strength/confidence of that polarity. Use 0 for neutral, mixed, or off-topic items.
- relevance: a number in [0, 1] for how directly this item bears on the named \
company's fundamentals or stock. A passing mention scores low; a company-specific \
material development scores high.
- event_type: exactly one label from this fixed taxonomy: {", ".join(EVENT_TAXONOMY)}. \
Use "other" when nothing fits; use "macro" for market-wide or sector-wide items \
that are not company-specific.
- rationale: one short sentence (for human audit) explaining the call.

Judge only from the text provided. Do not speculate beyond it. Be conservative: \
when the item is vague or only tangentially related, lower the relevance rather \
than inventing a strong sentiment."""


def build_user_text(headline: str, body: str) -> str:
    """Render the per-article user message (the volatile, non-cached suffix)."""
    headline = (headline or "").strip()
    body = (body or "").strip()
    return f"Headline: {headline}\n\nBody: {body}"
