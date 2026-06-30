"""Phase 5 M3 — news_annotations table (LLM annotation cache + cost surface).

Additive only — creates ``news_annotations``. The (content_hash, prompt_version)
unique constraint is the content-hash cache key: an unchanged article under an
unchanged prompt is never re-classified or re-billed. Every row records billed
token usage and real cost so the ablation's cost charge is honest (§5).

Revision ID: 0007_phase5_annotations
Revises: 0006_phase5_news
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_phase5_annotations"
down_revision: str | None = "0006_phase5_news"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_annotations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("sentiment", sa.Float(), nullable=True),
        sa.Column("relevance", sa.Float(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("batch", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "content_hash", "prompt_version", name="uq_news_annotation_content_prompt"
        ),
    )
    op.create_index(
        "ix_news_annotations_content_hash", "news_annotations", ["content_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_news_annotations_content_hash", table_name="news_annotations")
    op.drop_table("news_annotations")
