"""The structured annotation contract (Phase 5 M3).

One news item → one ``Annotation``: sentiment polarity+strength, an event-type
label from a fixed taxonomy, a relevance score, and a short rationale for
auditability. The JSON schema here drives the Claude structured-output config so
the fields are schema-validated rather than parsed from prose; the same schema
validates the stub's deterministic output, so both paths produce identical shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Fixed event taxonomy. Changing this set is a semantic change to the news
# feature spec and must bump the news feature-spec version (Phase 5 §3/M5).
EVENT_TAXONOMY: tuple[str, ...] = (
    "earnings",
    "guidance",
    "analyst_rating",
    "ma",  # merger / acquisition
    "legal_regulatory",
    "product",
    "management_change",
    "macro",
    "other",
)


@dataclass(frozen=True)
class Annotation:
    """A schema-validated annotation of one article's text.

    ``sentiment`` is in [-1, 1] (sign = polarity, magnitude = strength).
    ``relevance`` is in [0, 1]. ``event_type`` is one of ``EVENT_TAXONOMY``.
    """

    sentiment: float
    relevance: float
    event_type: str
    rationale: str


# JSON schema passed to Claude's output_config.format. additionalProperties is
# false and every field required, so the model cannot omit or invent fields.
ANNOTATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sentiment": {"type": "number"},
        "relevance": {"type": "number"},
        "event_type": {"type": "string", "enum": list(EVENT_TAXONOMY)},
        "rationale": {"type": "string"},
    },
    "required": ["sentiment", "relevance", "event_type", "rationale"],
}


class AnnotationSchemaError(ValueError):
    """A raw annotation dict did not satisfy the annotation contract."""


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def parse_annotation(raw: dict[str, Any]) -> Annotation:
    """Validate and normalize a raw annotation dict into an ``Annotation``.

    Coerces numeric strings, clamps ``sentiment`` to [-1, 1] and ``relevance`` to
    [0, 1] (the model can drift slightly out of range), and rejects an
    out-of-taxonomy ``event_type``. Raises ``AnnotationSchemaError`` on anything
    it can't repair.
    """
    for field in ("sentiment", "relevance", "event_type", "rationale"):
        if field not in raw:
            raise AnnotationSchemaError(f"Annotation missing field '{field}'.")

    try:
        sentiment = _clamp(float(raw["sentiment"]), -1.0, 1.0)
        relevance = _clamp(float(raw["relevance"]), 0.0, 1.0)
    except (TypeError, ValueError) as exc:
        raise AnnotationSchemaError("sentiment/relevance must be numeric.") from exc

    event_type = str(raw["event_type"])
    if event_type not in EVENT_TAXONOMY:
        raise AnnotationSchemaError(
            f"event_type '{event_type}' is not in the taxonomy."
        )

    return Annotation(
        sentiment=sentiment,
        relevance=relevance,
        event_type=event_type,
        rationale=str(raw["rationale"]),
    )
