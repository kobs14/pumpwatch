"""DlqEntry model: tokens whose fetch_token task hit its retry cap.

One row per failing ``token_address``. Re-failures bump ``attempts`` and
``last_seen`` via the ``UNIQUE(token_address)`` upsert in the repo —
duplicates are not inserted. No foreign key to ``tokens`` because DLQ
rows must remain inspectable after a token row is deleted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from pumpwatch.db.base import Base


class DlqEntry(Base):
    """One token's persistent fetch failure."""

    __tablename__ = "dlq_entries"
    __table_args__ = (UniqueConstraint("token_address", name="uq_dlq_entries_token_address"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
