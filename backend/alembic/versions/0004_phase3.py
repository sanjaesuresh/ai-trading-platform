"""Phase 3: paper-trading tables (deployments, orders, fills, snapshots, recon).

Additive only — creates the seven Phase 3 tables and their indexes. No existing
Phase 1/2 table or column is touched, so the change is forward- and backward-
compatible and the downgrade is a clean drop in reverse-dependency order.

Revision ID: 0004_phase3
Revises: 0003_phase2_m5
Create Date: 2026-06-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase3"
down_revision: str | None = "0003_phase2_m5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_deployments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("starting_capital", sa.Float(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("halt_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Integer(), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("client_order_id", sa.String(length=128), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("intended_quantity", sa.Float(), nullable=False),
        sa.Column("intended_notional", sa.Float(), nullable=False),
        sa.Column("reference_price", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("filled_quantity", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["paper_deployments.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_paper_orders_deployment_id", "paper_orders", ["deployment_id"])
    op.create_index("ix_paper_orders_trading_day", "paper_orders", ["trading_day"])
    # Unique: the deterministic client order id is the idempotency key — the DB
    # rejects a double-submit even if two passes race.
    op.create_index(
        "ix_paper_orders_client_order_id", "paper_orders", ["client_order_id"],
        unique=True,
    )

    op.create_table(
        "paper_fills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("broker_fill_id", sa.String(length=128), nullable=True),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("modeled_reference_price", sa.Float(), nullable=False),
        sa.Column("slippage_delta", sa.Float(), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["paper_deployments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["paper_orders.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_paper_fills_deployment_id", "paper_fills", ["deployment_id"])
    op.create_index("ix_paper_fills_order_id", "paper_fills", ["order_id"])
    op.create_index("ix_paper_fills_trading_day", "paper_fills", ["trading_day"])

    op.create_table(
        "paper_position_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Integer(), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("avg_entry_price", sa.Float(), nullable=False),
        sa.Column("market_value", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["paper_deployments.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_paper_position_snapshots_deployment_id",
        "paper_position_snapshots", ["deployment_id"],
    )
    op.create_index(
        "ix_paper_position_snapshots_trading_day",
        "paper_position_snapshots", ["trading_day"],
    )

    op.create_table(
        "paper_portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Integer(), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("position_value", sa.Float(), nullable=False),
        sa.Column("gross_exposure_pct", sa.Float(), nullable=False),
        sa.Column("drawdown_pct", sa.Float(), nullable=False),
        sa.Column("peak_equity", sa.Float(), nullable=False),
        sa.Column("num_positions", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["paper_deployments.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_paper_portfolio_snapshots_deployment_id",
        "paper_portfolio_snapshots", ["deployment_id"],
    )
    op.create_index(
        "ix_paper_portfolio_snapshots_trading_day",
        "paper_portfolio_snapshots", ["trading_day"],
    )

    op.create_table(
        "paper_reconciliation_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Integer(), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["paper_deployments.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_paper_reconciliation_logs_deployment_id",
        "paper_reconciliation_logs", ["deployment_id"],
    )
    op.create_index(
        "ix_paper_reconciliation_logs_trading_day",
        "paper_reconciliation_logs", ["trading_day"],
    )

    op.create_table(
        "system_flags",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_flags")
    op.drop_index(
        "ix_paper_reconciliation_logs_trading_day",
        table_name="paper_reconciliation_logs",
    )
    op.drop_index(
        "ix_paper_reconciliation_logs_deployment_id",
        table_name="paper_reconciliation_logs",
    )
    op.drop_table("paper_reconciliation_logs")
    op.drop_index(
        "ix_paper_portfolio_snapshots_trading_day",
        table_name="paper_portfolio_snapshots",
    )
    op.drop_index(
        "ix_paper_portfolio_snapshots_deployment_id",
        table_name="paper_portfolio_snapshots",
    )
    op.drop_table("paper_portfolio_snapshots")
    op.drop_index(
        "ix_paper_position_snapshots_trading_day",
        table_name="paper_position_snapshots",
    )
    op.drop_index(
        "ix_paper_position_snapshots_deployment_id",
        table_name="paper_position_snapshots",
    )
    op.drop_table("paper_position_snapshots")
    op.drop_index("ix_paper_fills_trading_day", table_name="paper_fills")
    op.drop_index("ix_paper_fills_order_id", table_name="paper_fills")
    op.drop_index("ix_paper_fills_deployment_id", table_name="paper_fills")
    op.drop_table("paper_fills")
    op.drop_index("ix_paper_orders_client_order_id", table_name="paper_orders")
    op.drop_index("ix_paper_orders_trading_day", table_name="paper_orders")
    op.drop_index("ix_paper_orders_deployment_id", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_table("paper_deployments")
