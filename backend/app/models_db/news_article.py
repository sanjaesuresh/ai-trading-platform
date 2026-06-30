"""Stored news article (Phase 5 M2).

One row per (symbol, provider item, content) triple. The
``(symbol, item_id, content_hash)`` unique constraint is the idempotency key:

- An exact re-ingest of the same article converges (ON CONFLICT DO NOTHING).
- A **revised** body produces a new ``content_hash`` and therefore a new row — a
  new availability event at its own ``first_seen_at``, never back-dated onto the
  original publish bar (plan §2). This is what makes the availability-time cutoff
  enforceable.
- The same article id attributed to several symbols (one macro headline hitting
  many tickers) is stored once per symbol, because ``symbol`` is part of the key.

``first_seen_at`` is the load-bearing column: the availability time the feature
builder keys on is ``max(published_at, first_seen_at)``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models_db.base import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "item_id", "content_hash", name="uq_news_symbol_item_content"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Both tz-aware UTC. published_at = vendor publish time; first_seen_at =
    # crawl/ingest time. The cutoff keys on max(published_at, first_seen_at).
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    headline: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # sha256 of (headline, body) — the cache/dedup key M3 extends with the prompt
    # version to decide whether an article needs (re)annotation.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Ingest provenance.
    provider: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
