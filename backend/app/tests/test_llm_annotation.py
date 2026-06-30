"""Unit tests for the LLM annotation core (DB-free, network-free, key-free).

Covers the structured-output schema, cost accounting, content-hash cache, and the
deterministic stub client. The real Claude client is not exercised here (it would
need the anthropic SDK + a key); the stub is the contract the tests pin.
"""

from __future__ import annotations

import pytest

from app.llm.cache import cache_key, filter_uncached
from app.llm.client import (
    AnnotationRequest,
    StubAnnotationClient,
    build_annotation_client,
)
from app.llm.cost import (
    BATCH_MULTIPLIER,
    PRICING,
    TokenUsage,
    UnknownModelPricingError,
    annotation_cost,
)
from app.llm.prompt import PROMPT_VERSION
from app.llm.schema import (
    ANNOTATION_JSON_SCHEMA,
    EVENT_TAXONOMY,
    AnnotationSchemaError,
    parse_annotation,
)

# --- schema ---


def test_parse_annotation_valid() -> None:
    ann = parse_annotation(
        {"sentiment": 0.5, "relevance": 0.9, "event_type": "earnings", "rationale": "x"}
    )
    assert ann.sentiment == 0.5
    assert ann.event_type == "earnings"


def test_parse_annotation_clamps_out_of_range() -> None:
    ann = parse_annotation(
        {"sentiment": 5.0, "relevance": -1.0, "event_type": "macro", "rationale": "y"}
    )
    assert ann.sentiment == 1.0
    assert ann.relevance == 0.0


def test_parse_annotation_rejects_bad_event_type() -> None:
    with pytest.raises(AnnotationSchemaError):
        parse_annotation(
            {"sentiment": 0.0, "relevance": 0.5, "event_type": "nope", "rationale": "z"}
        )


def test_parse_annotation_rejects_missing_field() -> None:
    with pytest.raises(AnnotationSchemaError):
        parse_annotation({"sentiment": 0.0, "relevance": 0.5, "event_type": "macro"})


def test_json_schema_is_strict() -> None:
    assert ANNOTATION_JSON_SCHEMA["additionalProperties"] is False
    assert set(ANNOTATION_JSON_SCHEMA["required"]) == {
        "sentiment",
        "relevance",
        "event_type",
        "rationale",
    }
    assert ANNOTATION_JSON_SCHEMA["properties"]["event_type"]["enum"] == list(
        EVENT_TAXONOMY
    )


# --- cost ---


def test_cost_is_token_metered_and_tier_aware() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    haiku = annotation_cost(usage, "claude-haiku-4-5", batch=False)
    sonnet = annotation_cost(usage, "claude-sonnet-4-6", batch=False)
    # Haiku: $1 in + $5 out = $6; Sonnet: $3 + $15 = $18.
    assert haiku == pytest.approx(6.0)
    assert sonnet == pytest.approx(18.0)


def test_batch_is_half_price() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    full = annotation_cost(usage, "claude-haiku-4-5", batch=False)
    batch = annotation_cost(usage, "claude-haiku-4-5", batch=True)
    assert batch == pytest.approx(full * BATCH_MULTIPLIER)


def test_cost_counts_cache_tokens() -> None:
    usage = TokenUsage(cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)
    cost = annotation_cost(usage, "claude-haiku-4-5", batch=False)
    p = PRICING["claude-haiku-4-5"]
    assert cost == pytest.approx(p.cache_read_per_mtok + p.cache_write_per_mtok)


def test_cost_unknown_model_raises() -> None:
    with pytest.raises(UnknownModelPricingError):
        annotation_cost(TokenUsage(input_tokens=1), "made-up-model", batch=True)


# --- cache ---


def test_cache_key_combines_hash_and_prompt() -> None:
    assert cache_key("abc", "v1") == "abc:v1"


def test_filter_uncached_skips_existing_and_dedups() -> None:
    items = [("h1", "a"), ("h2", "b"), ("h1", "dup")]
    existing = {cache_key("h2", "v1")}
    out = filter_uncached(items, existing, prompt_version="v1")
    assert out == ["a"]  # h2 cached, h1 kept once (dup removed)


# --- stub client (end-to-end, no network) ---


def test_stub_client_is_deterministic() -> None:
    client = StubAnnotationClient()
    req = AnnotationRequest(content_hash="deadbeef0000", headline="h", body="b")
    bid1 = client.submit_batch([req])
    res1 = client.collect_batch(bid1)
    bid2 = client.submit_batch([req])
    res2 = client.collect_batch(bid2)
    assert res1 is not None and res2 is not None
    assert res1[0].annotation == res2[0].annotation


def test_stub_client_results_have_cost_and_provenance() -> None:
    client = StubAnnotationClient(model_id="claude-haiku-4-5")
    req = AnnotationRequest(
        content_hash="abc12345ffff", headline="Earnings beat", body="...", article_id=7
    )
    bid = client.submit_batch([req])
    results = client.collect_batch(bid)
    assert results is not None
    r = results[0]
    assert r.status == "ok"
    assert r.annotation is not None
    assert r.annotation.event_type in EVENT_TAXONOMY
    assert r.cost_usd > 0.0
    assert r.model_id == "claude-haiku-4-5"
    assert r.prompt_version == PROMPT_VERSION
    assert r.article_id == 7


def test_build_annotation_client_no_key_is_stub() -> None:
    client = build_annotation_client("")
    assert isinstance(client, StubAnnotationClient)
    assert client.name == "stub"
