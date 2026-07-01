"""Phase 5 M5 — ML model news provenance columns.

Additive only — adds nullable news-provenance columns to ``ml_models`` (§4): the
news feature-spec version, the annotation model id, the annotation prompt version,
and the named news-feature configuration. Price-only models leave them NULL, so a
price-plus-news result is reproducible exactly the way a price-only one already is,
and a result produced under a superseded prompt is identifiable.

Revision ID: 0008_phase5_ml_provenance
Revises: 0007_phase5_annotations
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_phase5_ml_provenance"
down_revision: str | None = "0007_phase5_annotations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ml_models",
        sa.Column("news_feature_spec_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ml_models",
        sa.Column("annotation_model_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ml_models",
        sa.Column("annotation_prompt_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ml_models",
        sa.Column("news_feature_config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ml_models", "news_feature_config")
    op.drop_column("ml_models", "annotation_prompt_version")
    op.drop_column("ml_models", "annotation_model_id")
    op.drop_column("ml_models", "news_feature_spec_version")
