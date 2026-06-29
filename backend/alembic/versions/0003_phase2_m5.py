"""Phase 2 M5: evaluation_runs table for parameter sweeps + walk-forward runs.

Creates evaluation_runs, the persisted aggregate for an out-of-sample evaluation.
Additive only — no existing table or column is touched, so the change is forward-
and backward-compatible and the downgrade is a clean drop.

Revision ID: 0003_phase2_m5
Revises: 0002_phase2_m1
Create Date: 2026-06-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase2_m5"
down_revision: str | None = "0002_phase2_m1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("objective", sa.String(length=64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_evaluation_runs_symbol", "evaluation_runs", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_symbol", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
