"""Phase 5 M2 — news article + news-ingestion audit tables.

Additive only — creates ``news_articles`` and ``news_ingestion_runs``. No
existing table or column is touched. The annotation table (M3) and any
ModelMetadata provenance columns (M5) are separate later migrations so each
milestone is independently reviewable.

The ``(symbol, item_id, content_hash)`` unique constraint is the idempotency +
revision key: identical content re-ingests as a no-op; a revised body lands as a
new row at its own first-seen (plan §2).

Revision ID: 0006_phase5_news
Revises: 0005_phase4_ml
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase5_news"
down_revision: str | None = "0005_phase4_ml"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "symbol", "item_id", "content_hash", name="uq_news_symbol_item_content"
        ),
    )
    op.create_index("ix_news_articles_symbol", "news_articles", ["symbol"])
    op.create_index("ix_news_articles_content_hash", "news_articles", ["content_hash"])

    op.create_table(
        "news_ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=True),
        sa.Column("range_end", sa.Date(), nullable=True),
        sa.Column("items_fetched", sa.Integer(), nullable=True),
        sa.Column("items_written", sa.Integer(), nullable=True),
        sa.Column("items_dropped", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("news_ingestion_runs")
    op.drop_index("ix_news_articles_content_hash", table_name="news_articles")
    op.drop_index("ix_news_articles_symbol", table_name="news_articles")
    op.drop_table("news_articles")
