"""Unit tests for Prometheus metric handles + scrape output."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Any, cast

import fakeredis
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from prometheus_client import generate_latest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from pumpwatch.db.repos.dlq import DlqRepository
from pumpwatch.observability import tasks as obs_tasks
from pumpwatch.observability.metrics import (
    ALERTS_FIRED,
    ALERTS_SUPPRESSED,
    DLQ_SIZE,
    SOURCE_CALLS,
)


@pytest_asyncio.fixture
async def metrics_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE dlq_entries RESTART IDENTITY"))
    yield async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE dlq_entries RESTART IDENTITY"))


def test_alerts_fired_counter_increments_and_renders() -> None:
    """A label increment must show up in the scrape text output."""
    ALERTS_FIRED.labels(type="GROWTH_HIT").inc()
    text_output = generate_latest().decode("utf-8")
    assert "pumpwatch_alerts_fired_total" in text_output
    assert 'type="GROWTH_HIT"' in text_output


def test_alerts_suppressed_counter_renders() -> None:
    ALERTS_SUPPRESSED.labels(reason="muted").inc()
    text_output = generate_latest().decode("utf-8")
    assert "pumpwatch_alerts_suppressed_total" in text_output
    assert 'reason="muted"' in text_output


def test_source_calls_counter_renders_by_status() -> None:
    SOURCE_CALLS.labels(source="pumpfun", status="ok").inc()
    SOURCE_CALLS.labels(source="dexscreener", status="unavailable").inc()
    text_output = generate_latest().decode("utf-8")
    assert 'source="pumpfun"' in text_output
    assert 'status="unavailable"' in text_output


def test_dlq_size_gauge_renders() -> None:
    DLQ_SIZE.set(7)
    text_output = generate_latest().decode("utf-8")
    assert "pumpwatch_dlq_size" in text_output


async def test_refresh_gauges_pulls_from_postgres_and_redis(
    metrics_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: seed DLQ rows + a queue; refresh_gauges sets both gauges."""
    async with metrics_sessionmaker() as session, session.begin():
        repo = DlqRepository(session)
        await repo.upsert("addrA", "boom")
        await repo.upsert("addrB", "boom")

    fake = cast(aioredis.Redis, fakeredis.FakeAsyncRedis())
    await cast(Awaitable[int], fake.rpush("default", "task1", "task2", "task3"))
    await cast(Awaitable[int], fake.rpush("high", "task1"))

    monkeypatch.setattr(obs_tasks, "get_sessionmaker", lambda: metrics_sessionmaker)
    monkeypatch.setattr(obs_tasks, "_build_redis_client", lambda: fake)

    counts = await obs_tasks._refresh_async()
    assert counts["dlq_size"] == 2
    assert counts["queue_default"] == 3
    assert counts["queue_high"] == 1
    assert counts["queue_medium"] == 0
    assert counts["queue_low"] == 0


def test_start_metrics_server_handles_port_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server-start helper must never raise; a bind failure logs + returns."""
    from pumpwatch.observability import metrics as metrics_mod

    monkeypatch.setattr(metrics_mod, "_metrics_started", False)

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("address already in use")

    monkeypatch.setattr(
        "prometheus_client.start_http_server",
        _boom,
    )

    # Must not raise.
    metrics_mod.start_metrics_server(0)
