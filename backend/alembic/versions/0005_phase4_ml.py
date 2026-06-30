"""Phase 4 ML: ml_models registry table.

Additive only — creates the ``ml_models`` table that mirrors ``registry.ModelMetadata``
for the API layer. No existing Phase 1–3 table or column is touched; ML evaluation
runs reuse the existing ``evaluation_runs`` table with the new kind values
``"ml_walk_forward"`` and ``"ml_backtest"``, carrying ml params inside the existing
``config`` JSON column (no column changes there).

Revision ID: 0005_phase4_ml
Revises: 0004_phase3
Create Date: 2026-06-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase4_ml"
down_revision: str | None = "0004_phase3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ml_models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("feature_spec_version", sa.String(length=32), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("train_start", sa.String(length=64), nullable=False),
        sa.Column("train_end", sa.String(length=64), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("deadband", sa.Float(), nullable=False),
        sa.Column("lgbm_params", sa.JSON(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("num_threads", sa.Integer(), nullable=False),
        sa.Column("calibration", sa.String(length=32), nullable=False),
        sa.Column("calibrated", sa.Boolean(), nullable=False),
        sa.Column("enter_threshold", sa.Float(), nullable=False),
        sa.Column("exit_threshold", sa.Float(), nullable=False),
        sa.Column("min_hold", sa.Integer(), nullable=False),
        sa.Column("n_fit", sa.Integer(), nullable=False),
        sa.Column("n_calib", sa.Integer(), nullable=False),
        sa.Column("n_thresh", sa.Integer(), nullable=False),
        sa.Column("effective_n", sa.Float(), nullable=False),
        sa.Column("selection_config", sa.JSON(), nullable=False),
        sa.Column("validation_metrics", sa.JSON(), nullable=False),
        sa.Column("code_git_hash", sa.String(length=64), nullable=False),
        sa.Column("code_dirty", sa.Boolean(), nullable=False),
        sa.Column("code_diff_hash", sa.Text(), nullable=True),
        sa.Column("artifact_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ml_models_model_id", "ml_models", ["model_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ml_models_model_id", table_name="ml_models")
    op.drop_table("ml_models")
