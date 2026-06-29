"""OHLCV bar storage, extended in Phase 2 with adjusted prices and corporate actions.

The (symbol, timestamp) unique constraint is the idempotency key for upserts; the
btree backing it also serves (symbol, date-range) reads used by backtests.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models_db.base import Base


class MarketData(Base):
    __tablename__ = "market_data"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uq_symbol_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)

    # Phase 2: adjusted prices and corporate-action fields.
    # Nullable so existing rows remain valid after migration; new rows should populate all three.
    adj_close: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    div_cash: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    split_factor: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
