"""AlertSent model: persisted record of every alert fired by the alert engine."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpwatch.db.base import Base
from pumpwatch.db.enums import AlertType

if TYPE_CHECKING:
    from pumpwatch.db.models.subscription import Subscription


_ALERT_TYPE_VALUES = ", ".join(f"'{a.value}'" for a in AlertType)


class AlertSent(Base):
    """Every alert the engine fires is persisted here before delivery."""

    __tablename__ = "alerts_sent"
    __table_args__ = (
        CheckConstraint(f"alert_type IN ({_ALERT_TYPE_VALUES})", name="ck_alerts_sent_alert_type"),
        Index(
            "ix_alerts_sent_subscription_created",
            "subscription_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type: Mapped[AlertType] = mapped_column(String(32), nullable=False)
    triggered_at_market_cap: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    delivered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    subscription: Mapped[Subscription] = relationship(back_populates="alerts")
