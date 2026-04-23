"""ApiCallLog model: observability trace of every outbound API call."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from pumpwatch.db.base import Base


class ApiCallLog(Base):
    """One row per external API call — used to debug client behavior at runtime."""

    __tablename__ = "api_call_log"
    __table_args__ = (Index("ix_api_call_log_source_ts", "source", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
