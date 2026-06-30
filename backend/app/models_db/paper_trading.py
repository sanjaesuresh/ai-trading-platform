"""Phase 3 paper-trading persistence models.

One cohesive set of tables for the paper-trading deployment lifecycle:

- ``PaperDeployment`` — a strategy bound to a basket, capital, and risk limits.
- ``PaperOrder`` / ``PaperFill`` — submitted orders and their realized fills.
  Each fill records the backtest-modeled reference price and the realized-minus-
  modeled slippage delta (implementation shortfall) so the comparison view and the
  §13.2 calibration loop read persisted data rather than recompute it.
- ``PaperPositionSnapshot`` / ``PortfolioSnapshot`` — per-day positions and the
  portfolio's equity / exposure / drawdown, so the live equity curve is reproducible.
- ``ReconciliationLog`` — recorded divergences between intended and broker-reported
  state (broker is the source of truth for accounting).
- ``SystemFlag`` — small key/value control table; holds the global kill switch.

Money/quantity fields are ``Float`` to match the rest of the schema (research
tool, simulated only). Foreign keys cascade so deleting a deployment cleans up
its children.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models_db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PaperDeployment(Base):
    __tablename__ = "paper_deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Strategy params and the symbol basket as JSON blobs.
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    symbols: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    starting_capital: Mapped[float] = mapped_column(Float, nullable=False)
    # The PortfolioConfig sizing / cost / risk-limit knobs (everything except
    # initial_capital, which is starting_capital above).
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Per-deployment enable flag and lifecycle status ("active" / "halted").
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    orders: Mapped[list[PaperOrder]] = relationship(
        "PaperOrder", back_populates="deployment",
        cascade="all, delete-orphan", order_by="PaperOrder.id",
    )
    portfolio_snapshots: Mapped[list[PortfolioSnapshot]] = relationship(
        "PortfolioSnapshot", back_populates="deployment",
        cascade="all, delete-orphan", order_by="PortfolioSnapshot.trading_day",
    )


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("paper_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    trading_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Deterministic per (deployment, symbol, day, side) — the idempotency key so a
    # re-run reconciles to the existing order rather than double-submitting. UNIQUE
    # so the DB enforces no double-submit even under concurrent submit passes.
    client_order_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY / SELL
    intended_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    intended_notional: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Decision-time reference price (latest close) used to size and as the
    # provisional slippage benchmark; the fill stores the modeled open it lands on.
    reference_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="new")
    filled_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    deployment: Mapped[PaperDeployment] = relationship(
        "PaperDeployment", back_populates="orders"
    )
    fills: Mapped[list[PaperFill]] = relationship(
        "PaperFill", back_populates="order",
        cascade="all, delete-orphan", order_by="PaperFill.id",
    )


class PaperFill(Base):
    __tablename__ = "paper_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("paper_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    broker_fill_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)  # realized fill price

    # Slippage attribution (plan §3.2 / §11): the backtest's modeled open for this
    # fill date and the signed realized-minus-modeled delta (implementation
    # shortfall). Aggregated, the delta distribution IS the quantified backtest↔paper
    # gap surfaced in the comparison view.
    modeled_reference_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    filled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    order: Mapped[PaperOrder] = relationship("PaperOrder", back_populates="fills")


class PaperPositionSnapshot(Base):
    __tablename__ = "paper_position_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("paper_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    trading_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_entry_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    market_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class PortfolioSnapshot(Base):
    __tablename__ = "paper_portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("paper_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    trading_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    equity: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    position_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    gross_exposure_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    num_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    deployment: Mapped[PaperDeployment] = relationship(
        "PaperDeployment", back_populates="portfolio_snapshots"
    )


class ReconciliationLog(Base):
    __tablename__ = "paper_reconciliation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("paper_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    trading_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # e.g. "partial_fill", "reject", "unexpected_position", "missing_position",
    # "position_mismatch", "cash_mismatch".
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class SystemFlag(Base):
    """Small key/value control table. Holds the global kill switch
    (``name="global_kill"``, ``value={"active": bool, "reason": str}``)."""

    __tablename__ = "system_flags"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
