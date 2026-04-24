"""Celery tasks for the scheduler service.

Two tasks:
  - ``fetch_batch`` — Beat-triggered. Rebuilds the per-token poll set,
    persists per-sub priority, dispatches one ``fetch_token`` per token.
  - ``fetch_token`` — runs against the price source, logs the call, returns.
    This session's body is intentionally a thin shell; Session 5 expands it
    to write ``PriceSnapshot`` rows and push to the Redis hot cache.

Sync wrappers use ``asyncio.run`` so each Celery worker thread gets a
fresh event loop. Building the DB sessionmaker and the price-source client
inside the async helpers (not at module scope) keeps imports cheap and
avoids the eager-init footgun called out in Session 1.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.celery_app import celery
from pumpwatch.config import get_settings
from pumpwatch.db.enums import Priority
from pumpwatch.db.repos.price_snapshot import PriceSnapshotRepository
from pumpwatch.db.repos.subscription import SubscriptionRepository
from pumpwatch.db.session import get_sessionmaker
from pumpwatch.logging import get_logger
from pumpwatch.scheduler.batch import BatchItem, build_batch
from pumpwatch.sources.pumpfun import PumpFunClient

_log = get_logger(__name__)


def _redact(address: str) -> str:
    return f"{address[:4]}...{address[-4:]}" if len(address) > 8 else address


def _build_pumpfun_client(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> PumpFunClient:
    """Factory used by the fetch task. Tests monkey-patch this to inject a fake."""
    settings = get_settings()
    return PumpFunClient(
        settings,
        sessionmaker=sessionmaker,
        log_calls=settings.PUMPFUN_LOG_CALLS,
    )


def _group_assignments_by_tier(
    items: list[BatchItem],
) -> Mapping[Priority, list[int]]:
    """Pivot per-item ``(sub_id, tier)`` lists into ``{tier: [sub_id, ...]}``."""
    by_tier: dict[Priority, list[int]] = defaultdict(list)
    for item in items:
        for sub_id, tier in item.subscription_priorities:
            by_tier[tier].append(sub_id)
    return by_tier


async def _fetch_batch_async() -> dict[str, int]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = await SubscriptionRepository(session).list_active_with_tokens()
        addresses = [r.token_address for r in rows]
        snapshots = await PriceSnapshotRepository(session).recent_per_token(addresses, limit=20)

    items = build_batch(rows, snapshots, now=datetime.now(UTC))

    if items:
        # Short, dedicated session for the bulk priority update so we don't
        # hold the read connection while we dispatch tasks.
        async with sessionmaker() as session, session.begin():
            await SubscriptionRepository(session).set_priorities(_group_assignments_by_tier(items))

    counts = {"tokens": len(items), "high": 0, "medium": 0, "low": 0}
    for item in items:
        # apply_async routes to the named queue; eager-mode tests ignore
        # this and run inline (see tests/celery_helpers.py).
        fetch_token.apply_async(args=[item.token_address], queue=item.tier.value)
        if item.tier is Priority.HIGH:
            counts["high"] += 1
        elif item.tier is Priority.MEDIUM:
            counts["medium"] += 1
        else:
            counts["low"] += 1

    _log.info(
        "scheduler.fetch_batch.dispatched",
        tokens=counts["tokens"],
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
    )
    return counts


async def _fetch_token_async(token_address: str) -> dict[str, Any]:
    sessionmaker = get_sessionmaker()
    log = _log.bind(token=_redact(token_address))
    async with _build_pumpfun_client(sessionmaker) as client:
        snap = await client.fetch_one(token_address)
    log.info("scheduler.fetch_token.done", found=snap is not None)
    return {"address": token_address, "found": snap is not None}


@celery.task(name="pumpwatch.scheduler.fetch_batch", queue="default")  # type: ignore[untyped-decorator]
def fetch_batch() -> dict[str, int]:
    """Beat-triggered. Rebuilds the batch and dispatches per-token fetches."""
    return asyncio.run(_fetch_batch_async())


@celery.task(  # type: ignore[untyped-decorator]
    name="pumpwatch.scheduler.fetch_token",
    queue="default",
    acks_late=True,
)
def fetch_token(token_address: str) -> dict[str, Any]:
    """Fetch one token from the price source. Thin shell this session."""
    return asyncio.run(_fetch_token_async(token_address))
