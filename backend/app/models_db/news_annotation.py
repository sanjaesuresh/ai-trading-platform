"""Stored LLM annotation (Phase 5 M3).

One row per (content_hash, prompt_version) — the cache surface. The feature
builder (M4) joins annotations to articles on ``content_hash``, so an identical
article appearing under several symbols reuses one annotation (the §5 dedup), and
an unchanged article under an unchanged prompt is never re-classified.

Every row carries full provenance (model id, prompt version, content hash) so a
result is reproducible and the recorded **billed cost** is the honest spend the
ablation charges (§5/§6). Annotations that are billed but later dropped from
features (low relevance, parse failure) are still stored with their cost, so the
relevance cutoff cannot launder cost off the books.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models_db.base import Base


class NewsAnnotation(Base):
    __tablename__ = "news_annotations"
    __table_args__ = (
        UniqueConstraint(
            "content_hash", "prompt_version", name="uq_news_annotation_content_prompt"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Cache key + provenance.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional link to a representative article (provenance/debugging).
    article_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The annotation fields (nullable when status != "ok").
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Billed token usage and real cost (§5).
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    batch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # "ok" | "failed". Failed rows are billed-but-dropped, recorded for honesty.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
