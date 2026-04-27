"""Celery task that refreshes the periodic gauges.

Counters (alerts fired, suppressed, source calls) increment in-process
where they happen. Gauges that reflect *external* state — Celery queue
depth in Redis, DLQ row count in Postgres — need a periodic poll. This
task is Beat-scheduled at ``METRICS_GAUGE_REFRESH_SECONDS`` cadence.

Best-effort: a Postgres outage or Redis blip warns and continues so the
gauges go stale rather than the worker dying.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import cast

import redis.asyncio as aioredis

from pumpwatch.celery_app import celery
from pumpwatch.config import get_settings
from pumpwatch.db.repos.dlq import DlqRepository
from pumpwatch.db.session import get_sessionmaker
from pumpwatch.logging import get_logger
from pumpwatch.observability.metrics import CELERY_QUEUE_DEPTH, DLQ_SIZE

_log = get_logger(__name__)

# Celery+Redis broker stores per-queue task lists under the queue name
# (verify with ``redis-cli LLEN default``); the tuple matches the
# ``task_queues`` declaration in :mod:`pumpwatch.celery_app`.
_TRACKED_QUEUES = ("default", "high", "medium", "low")


def _build_redis_client() -> aioredis.Redis:
    """Per-invocation Redis client, mirroring the worker's pattern."""
    return aioredis.from_url(str(get_settings().REDIS_URL))


async def _refresh_async() -> dict[str, int]:
    counts: dict[str, int] = {}

    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            dlq_count = await DlqRepository(session).count()
        DLQ_SIZE.set(dlq_count)
        counts["dlq_size"] = dlq_count
    except Exception as exc:  # noqa: BLE001 — best-effort
        _log.warning("observability.refresh.dlq_failed", error=str(exc))

    client: aioredis.Redis | None = None
    try:
        client = _build_redis_client()
    except Exception as exc:  # noqa: BLE001 — best-effort, skip queue gauges
        _log.warning("observability.refresh.redis_connect_failed", error=str(exc))
        return counts

    try:
        for queue in _TRACKED_QUEUES:
            try:
                depth = await cast(Awaitable[int], client.llen(queue))
                CELERY_QUEUE_DEPTH.labels(queue=queue).set(depth)
                counts[f"queue_{queue}"] = depth
            except Exception as exc:  # noqa: BLE001 — best-effort per-queue
                _log.warning(
                    "observability.refresh.queue_failed",
                    queue=queue,
                    error=str(exc),
                )
    finally:
        try:
            await client.aclose()
        except Exception as exc:  # noqa: BLE001 — best-effort
            _log.warning("observability.refresh.redis_close_failed", error=str(exc))

    return counts


@celery.task(  # type: ignore[untyped-decorator]
    name="pumpwatch.observability.refresh_gauges",
    queue="default",
)
def refresh_gauges() -> dict[str, int]:
    """Poll Postgres + Redis once and update the dlq/queue-depth gauges."""
    return asyncio.run(_refresh_async())
