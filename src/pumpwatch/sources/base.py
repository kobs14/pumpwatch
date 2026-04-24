"""Shared contract for every price data source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import TracebackType
from typing import Protocol, Self


@dataclass(frozen=True, slots=True)
class TokenSnapshot:
    """Normalized point-in-time market snapshot.

    Every data source produces this shape — the rest of the system never sees
    raw upstream JSON. Missing fields from the upstream become ``None`` here.
    """

    address: str
    symbol: str | None
    name: str | None
    market_cap_usd: Decimal | None
    price_usd: Decimal | None
    volume_5m_usd: Decimal | None
    liquidity_usd: Decimal | None
    holder_count: int | None
    source: str
    fetched_at: datetime


class PriceDataSource(Protocol):
    """Protocol every concrete price source implements."""

    name: str

    async def fetch_one(self, address: str) -> TokenSnapshot | None:
        """Return a snapshot for one address, or ``None`` if upstream has no data."""
        ...

    async def fetch_batch(self, addresses: list[str]) -> dict[str, TokenSnapshot]:
        """Return a dict keyed by address; missing addresses are simply absent."""
        ...

    async def close(self) -> None:
        """Release any owned resources (HTTP session, etc.). Idempotent."""
        ...

    async def __aenter__(self) -> Self:
        """Enter an ``async with`` block; concrete sources may lazily open IO here."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the ``async with`` block; must call ``close()``."""
        ...
