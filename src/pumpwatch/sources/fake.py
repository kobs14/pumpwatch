"""In-memory ``PriceDataSource`` for tests."""

from __future__ import annotations

import asyncio
import random
from types import TracebackType
from typing import Self

from pumpwatch.sources.base import TokenSnapshot
from pumpwatch.sources.exceptions import PumpFunUnavailableError


class FakePriceDataSource:
    """Deterministic, scriptable implementation of ``PriceDataSource``.

    Each address is given an ordered history of snapshots that ``fetch_one``
    consumes in order. When the list is exhausted the last snapshot is
    returned on every subsequent call — useful for "price is now steady"
    test scenarios.
    """

    name: str = "fake"

    def __init__(
        self,
        snapshots: dict[str, list[TokenSnapshot]],
        fail_addresses: set[str] | None = None,
        failure_rate: float = 0.0,
        latency_ms: int = 0,
    ) -> None:
        # Copy lists so callers can't mutate our state after construction.
        self._snapshots: dict[str, list[TokenSnapshot]] = {
            addr: list(hist) for addr, hist in snapshots.items()
        }
        self._cursors: dict[str, int] = dict.fromkeys(snapshots, 0)
        self._fail_addresses: set[str] = set(fail_addresses or ())
        self._failure_rate = failure_rate
        self._latency_ms = latency_ms
        self._rng = random.Random(1337)

    async def fetch_one(self, address: str) -> TokenSnapshot | None:
        if self._latency_ms > 0:
            await asyncio.sleep(self._latency_ms / 1000)

        if address in self._fail_addresses:
            raise PumpFunUnavailableError(f"fake forced failure for {address}")

        if self._failure_rate > 0 and self._rng.random() < self._failure_rate:
            raise PumpFunUnavailableError(f"fake random failure for {address}")

        history = self._snapshots.get(address)
        if not history:
            return None

        idx = self._cursors[address]
        snapshot = history[min(idx, len(history) - 1)]
        if idx < len(history) - 1:
            self._cursors[address] = idx + 1
        return snapshot

    async def fetch_batch(self, addresses: list[str]) -> dict[str, TokenSnapshot]:
        results = await asyncio.gather(
            *(self.fetch_one(a) for a in addresses),
            return_exceptions=True,
        )
        out: dict[str, TokenSnapshot] = {}
        for address, result in zip(addresses, results, strict=True):
            if isinstance(result, TokenSnapshot):
                out[address] = result
        return out

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()


def make_fake_source(
    snapshots: dict[str, list[TokenSnapshot]],
) -> FakePriceDataSource:
    """Convenience factory used by tests."""
    return FakePriceDataSource(snapshots)
