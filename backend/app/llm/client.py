"""Annotation clients (Phase 5 M3).

Two-phase batch contract — ``submit_batch`` enqueues the day's articles and
returns a batch handle; ``collect_batch`` retrieves completed annotations (or
``None`` while the batch is still running). This mirrors the existing paper
submit/reconcile cron split (§5); the cron wiring is M7.

- ``StubAnnotationClient`` — deterministic, no network, no key. The only client
  the test suite touches. Returns annotations derived from the content hash and
  synthetic-but-deterministic token usage so the cost pipeline is exercised.
- ``ClaudeBatchAnnotationClient`` — real Batch API, structured outputs, prompt
  caching, token-metered cost. Imports the ``anthropic`` SDK lazily so this
  module imports with no SDK installed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.llm.cost import TokenUsage, annotation_cost
from app.llm.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_user_text
from app.llm.schema import (
    ANNOTATION_JSON_SCHEMA,
    EVENT_TAXONOMY,
    Annotation,
    AnnotationSchemaError,
    parse_annotation,
)


@dataclass(frozen=True)
class AnnotationRequest:
    """One article to annotate, carrying its cache identity and provenance link."""

    content_hash: str
    headline: str
    body: str
    article_id: int | None = None


@dataclass(frozen=True)
class AnnotationResult:
    """The outcome of one annotation call — billed whether or not it succeeded."""

    content_hash: str
    article_id: int | None
    annotation: Annotation | None  # None when the call failed to parse
    usage: TokenUsage
    cost_usd: float
    model_id: str
    prompt_version: str
    status: str  # "ok" | "failed"
    error: str | None = None


class AnnotationClient(ABC):
    """Two-phase batch annotation contract."""

    model_id: str
    batch: bool

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier recorded in logs."""
        raise NotImplementedError

    @abstractmethod
    def submit_batch(self, requests: list[AnnotationRequest]) -> str:
        """Enqueue *requests* as one batch; return an opaque batch handle."""
        raise NotImplementedError

    @abstractmethod
    def collect_batch(self, batch_id: str) -> list[AnnotationResult] | None:
        """Return results for *batch_id*, or ``None`` if still running."""
        raise NotImplementedError


def _stub_annotation(content_hash: str, *, relevance_floor: float = 0.0) -> Annotation:
    """Deterministic annotation derived from the content hash (no network)."""
    seed = int(content_hash[:8], 16)
    sentiment = ((seed % 2001) - 1000) / 1000.0  # [-1, 1]
    relevance = max(relevance_floor, (seed % 1001) / 1000.0)  # [0, 1]
    event_type = EVENT_TAXONOMY[seed % len(EVENT_TAXONOMY)]
    return Annotation(
        sentiment=sentiment,
        relevance=relevance,
        event_type=event_type,
        rationale="Deterministic stub annotation (no LLM call).",
    )


def _stub_usage(headline: str, body: str) -> TokenUsage:
    """Deterministic synthetic usage so the cost pipeline is exercised offline."""
    text_len = len((headline or "") + (body or ""))
    return TokenUsage(input_tokens=max(1, text_len // 4), output_tokens=32)


class StubAnnotationClient(AnnotationClient):
    """No-network deterministic client for tests, CI, and no-key environments."""

    def __init__(self, model_id: str = "claude-haiku-4-5", *, batch: bool = True) -> None:
        self.model_id = model_id
        self.batch = batch
        self._batches: dict[str, list[AnnotationRequest]] = {}
        self._counter = 0

    @property
    def name(self) -> str:
        return "stub"

    def submit_batch(self, requests: list[AnnotationRequest]) -> str:
        self._counter += 1
        batch_id = f"stub-batch-{self._counter}"
        self._batches[batch_id] = list(requests)
        return batch_id

    def collect_batch(self, batch_id: str) -> list[AnnotationResult] | None:
        requests = self._batches.get(batch_id)
        if requests is None:
            return []
        results: list[AnnotationResult] = []
        for req in requests:
            annotation = _stub_annotation(req.content_hash)
            usage = _stub_usage(req.headline, req.body)
            results.append(
                AnnotationResult(
                    content_hash=req.content_hash,
                    article_id=req.article_id,
                    annotation=annotation,
                    usage=usage,
                    cost_usd=annotation_cost(usage, self.model_id, batch=self.batch),
                    model_id=self.model_id,
                    prompt_version=PROMPT_VERSION,
                    status="ok",
                )
            )
        return results


class ClaudeBatchAnnotationClient(AnnotationClient):
    """Real Claude Batch API client (lazy-imports the anthropic SDK)."""

    def __init__(self, api_key: str, model_id: str = "claude-haiku-4-5") -> None:
        if not api_key:
            raise ValueError(
                "Anthropic API key is required for the Claude client; "
                "use StubAnnotationClient when no key is configured."
            )
        # Lazy import so this module loads without the anthropic SDK installed.
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model_id = model_id
        self.batch = True

    @property
    def name(self) -> str:
        return "claude_batch"

    def submit_batch(self, requests: list[AnnotationRequest]) -> str:
        from anthropic.types.message_create_params import (
            MessageCreateParamsNonStreaming,
        )
        from anthropic.types.messages.batch_create_params import Request

        batch_requests = []
        for idx, req in enumerate(requests):
            params = MessageCreateParamsNonStreaming(
                model=self.model_id,
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": ANNOTATION_JSON_SCHEMA,
                    }
                },
                messages=[
                    {
                        "role": "user",
                        "content": build_user_text(req.headline, req.body),
                    }
                ],
            )
            # custom_id maps the result back to the article's content hash.
            batch_requests.append(
                Request(custom_id=f"{idx}:{req.content_hash}", params=params)
            )

        batch = self._client.messages.batches.create(requests=batch_requests)
        return str(batch.id)

    def collect_batch(self, batch_id: str) -> list[AnnotationResult] | None:
        batch = self._client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            return None

        results: list[AnnotationResult] = []
        for entry in self._client.messages.batches.results(batch_id):
            content_hash = entry.custom_id.split(":", 1)[-1]
            result = entry.result
            if result.type != "succeeded":
                # Billed-but-failed annotations still count toward honest cost; a
                # failed entry carries no usage here, recorded as zero.
                results.append(
                    AnnotationResult(
                        content_hash=content_hash,
                        article_id=None,
                        annotation=None,
                        usage=TokenUsage(),
                        cost_usd=0.0,
                        model_id=self.model_id,
                        prompt_version=PROMPT_VERSION,
                        status="failed",
                        error=str(result.type),
                    )
                )
                continue

            message = result.message
            usage = _usage_from_message(message.usage)
            cost = annotation_cost(usage, self.model_id, batch=True)
            annotation, status, error = _parse_message(message)
            results.append(
                AnnotationResult(
                    content_hash=content_hash,
                    article_id=None,
                    annotation=annotation,
                    usage=usage,
                    cost_usd=cost,
                    model_id=self.model_id,
                    prompt_version=PROMPT_VERSION,
                    status=status,
                    error=error,
                )
            )
        return results


def _usage_from_message(raw_usage: object) -> TokenUsage:
    """Map an anthropic usage object into our TokenUsage (real billed tokens)."""
    return TokenUsage(
        input_tokens=int(getattr(raw_usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(raw_usage, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(raw_usage, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(
            getattr(raw_usage, "cache_creation_input_tokens", 0) or 0
        ),
    )


def _parse_message(message: object) -> tuple[Annotation | None, str, str | None]:
    """Extract and validate the structured annotation from a message."""
    import json

    text = ""
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = block.text
            break
    if not text:
        return None, "failed", "No text block in annotation response."
    try:
        annotation = parse_annotation(json.loads(text))
    except (ValueError, AnnotationSchemaError) as exc:
        return None, "failed", str(exc)
    return annotation, "ok", None


def build_annotation_client(
    api_key: str, model_id: str = "claude-haiku-4-5"
) -> AnnotationClient:
    """Return the real client when a key is configured, else the offline stub."""
    if api_key:
        return ClaudeBatchAnnotationClient(api_key, model_id=model_id)
    return StubAnnotationClient(model_id=model_id)
