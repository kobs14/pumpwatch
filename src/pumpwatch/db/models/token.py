"""Token model: a Solana token mint PumpWatch tracks."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpwatch.db.base import Base

if TYPE_CHECKING:
    from pumpwatch.db.models.price_snapshot import PriceSnapshot
    from pumpwatch.db.models.subscription import Subscription


class Token(Base):
    """A Solana token mint. The mint address is the natural primary key."""

    __tablename__ = "tokens"

    address: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="token",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    price_snapshots: Mapped[list[PriceSnapshot]] = relationship(
        back_populates="token",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
