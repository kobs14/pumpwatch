"""PriceSnapshot model: a normalized point-in-time market measurement."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpwatch.db.base import Base

if TYPE_CHECKING:
    from pumpwatch.db.models.token import Token


class PriceSnapshot(Base):
    """High-volume time-series table of per-token market snapshots.

    Plan to partition by day in a future migration once row count exceeds ~10M.
    """

    __tablename__ = "price_snapshots"
    __table_args__ = (
        Index(
            "ix_price_snapshots_token_ts",
            "token_address",
            "ts",
            postgresql_using="btree",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_address: Mapped[str] = mapped_column(
        Text,
        ForeignKey("tokens.address", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    market_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    volume_5m_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    holder_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="pumpfun", server_default="pumpfun"
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    token: Mapped[Token] = relationship(back_populates="price_snapshots")
