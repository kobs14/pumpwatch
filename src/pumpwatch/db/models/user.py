"""User model: a Telegram user who has onboarded to PumpWatch."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Numeric, Text, Time, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpwatch.db.base import Base

if TYPE_CHECKING:
    from pumpwatch.db.models.subscription import Subscription


class User(Base):
    """A Telegram user who has interacted with the bot."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_code: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="en", server_default="en"
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="UTC", server_default="UTC"
    )
    alerts_muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    default_growth_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("10.00"), server_default="10.00"
    )
    default_stoploss_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("15.00"), server_default="15.00"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
