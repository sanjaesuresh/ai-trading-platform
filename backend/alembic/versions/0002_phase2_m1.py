"""Phase 2 M1: adjusted prices, corporate-action fields, ingestion audit table.

Adds to market_data:
  - adj_close      Float  nullable (vendor adjusted close; NULL on pre-existing rows)
  - div_cash       Float  nullable (cash dividend per share; NULL on pre-existing rows)
  - split_factor   Float  nullable (split multiplier; NULL on pre-existing rows)

Creates ingestion_runs audit table.

Revision ID: 0002_phase2_m1
Revises: 0001_initial
Create Date: 2026-06-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase2_m1"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # market_data: add adjusted-price + corporate-action columns
    # ------------------------------------------------------------------
    # (symbol, date-range) reads are served by the btree backing the existing
    # uq_symbol_timestamp unique constraint, so no extra index is created here.
    op.add_column("market_data", sa.Column("adj_close", sa.Float(), nullable=True))
    op.add_column("market_data", sa.Column("div_cash", sa.Float(), nullable=True))
    op.add_column("market_data", sa.Column("split_factor", sa.Float(), nullable=True))

    # ------------------------------------------------------------------
    # ingestion_runs: new audit table
    # ------------------------------------------------------------------
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=True),
        sa.Column("range_end", sa.Date(), nullable=True),
        sa.Column("rows_fetched", sa.Integer(), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_runs_symbol", "ingestion_runs", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_symbol", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")

    op.drop_column("market_data", "split_factor")
    op.drop_column("market_data", "div_cash")
    op.drop_column("market_data", "adj_close")
