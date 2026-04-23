"""Subscription model: a user's interest in a token with alert thresholds."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpwatch.db.base import Base
from pumpwatch.db.enums import Priority, SubscriptionStatus

if TYPE_CHECKING:
    from pumpwatch.db.models.alert_sent import AlertSent
    from pumpwatch.db.models.token import Token
    from pumpwatch.db.models.user import User


_PRIORITY_VALUES = ", ".join(f"'{p.value}'" for p in Priority)
_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in SubscriptionStatus)


class Subscription(Base):
    """A user's subscription to a token with growth and stoploss thresholds."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "token_address", name="uq_subscriptions_user_token"),
        CheckConstraint(f"priority IN ({_PRIORITY_VALUES})", name="ck_subscriptions_priority"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="ck_subscriptions_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_address: Mapped[str] = mapped_column(
        Text,
        ForeignKey("tokens.address", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    growth_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    stoploss_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    warning_buffer_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("5.00"), server_default="5.00"
    )
    volume_spike_k: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("3.00"), server_default="3.00"
    )
    baseline_market_cap: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    priority: Mapped[Priority] = mapped_column(
        String(16),
        nullable=False,
        default=Priority.HIGH.value,
        server_default=Priority.HIGH.value,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        String(16),
        nullable=False,
        default=SubscriptionStatus.ACTIVE.value,
        server_default=SubscriptionStatus.ACTIVE.value,
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

    user: Mapped[User] = relationship(back_populates="subscriptions")
    token: Mapped[Token] = relationship(back_populates="subscriptions")
    alerts: Mapped[list[AlertSent]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
