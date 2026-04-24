"""Celery tasks for the scheduler service.

Two tasks:
  - ``fetch_batch`` — Beat-triggered. Rebuilds the per-token poll set,
    persists per-sub priority, dispatches one ``fetch_token`` per token.
  - ``fetch_token`` — runs against the configured ``PriceDataSource``,
    writes a ``PriceSnapshot`` row, updates the Redis hot cache, and
    publishes a ``pw:price.updated`` event. Source failure is a silent
    skip (the scheduler re-dispatches on the next tick). Cache and
    pub-sub writes are best-effort and cannot break the snapshot path.

Sync wrappers use ``asyncio.run`` so each Celery worker thread gets a
fresh event loop. Building the DB sessionmaker and the price-source
client inside the async helpers (not at module scope) keeps imports
cheap and avoids the eager-init footgun called out in Session 1.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.cache.redis_client import (
    PRICE_UPDATED_CHANNEL,
    cache_key_for,
    publish_price_updated,
    set_price_cache,
    ttl_for_tier,
)
from pumpwatch.celery_app import celery
from pumpwatch.config import get_settings
from pumpwatch.db.enums import Priority
from pumpwatch.db.models import PriceSnapshot
from pumpwatch.db.repos.price_snapshot import PriceSnapshotRepository
from pumpwatch.db.repos.subscription import SubscriptionRepository
from pumpwatch.db.session import get_sessionmaker
from pumpwatch.logging import get_logger
from pumpwatch.scheduler.batch import BatchItem, build_batch
from pumpwatch.sources.base import PriceDataSource, TokenSnapshot
from pumpwatch.sources.exceptions import PumpFunUnavailableError
from pumpwatch.sources.factory import build_source

_log = get_logger(__name__)

_TIER_RANK: dict[Priority, int] = {
    Priority.LOW: 0,
    Priority.MEDIUM: 1,
    Priority.HIGH: 2,
    # PAUSED must never win the max — if it ever ends up here the worker
    # treats it as LOW for TTL purposes (via the fallback below).
    Priority.PAUSED: -1,
}


def _redact(address: str) -> str:
    return f"{address[:4]}...{address[-4:]}" if len(address) > 8 else address


def _build_source(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> PriceDataSource:
    """Factory used by the fetch task. Tests monkey-patch this to inject a fake."""
    return build_source(sessionmaker)


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


async def _pick_tier_for_token(session: AsyncSession, token_address: str) -> Priority:
    """Return the current polling tier for a token.

    Max ``Subscription.priority`` across all active subs on this token,
    using the same rank table the batch builder uses. Falls back to
    ``LOW`` if no active subs are left (race: user stopped their last
    sub between scheduler dispatch and worker execution).
    """
    subs = await SubscriptionRepository(session).get_active_by_token(token_address)
    best: Priority = Priority.LOW
    for sub in subs:
        # ``sub.priority`` comes back as a plain str from the DB (see
        # Session 4 lesson). ``Priority(value)`` normalises it back.
        tier = Priority(sub.priority)
        if _TIER_RANK[tier] > _TIER_RANK[best]:
            best = tier
    return best


def _snapshot_from(snap: TokenSnapshot) -> PriceSnapshot:
    """Map a source-level ``TokenSnapshot`` into a DB-level row."""
    return PriceSnapshot(
        token_address=snap.address,
        market_cap_usd=snap.market_cap_usd,
        price_usd=snap.price_usd,
        volume_5m_usd=snap.volume_5m_usd,
        liquidity_usd=snap.liquidity_usd,
        holder_count=snap.holder_count,
        source=snap.source,
        ts=snap.fetched_at,
    )


def _cache_payload(snap: TokenSnapshot, tier: Priority) -> dict[str, Any]:
    """Build the JSON-serialisable hot-cache / pub-sub payload.

    ``Decimal`` and ``datetime`` are handled by the encoder's default
    hook so callers never stringify fields by hand.
    """
    return {
        "address": snap.address,
        "ts": snap.fetched_at,
        "source": snap.source,
        "tier": tier.value,
        "market_cap_usd": snap.market_cap_usd,
        "price_usd": snap.price_usd,
        "volume_5m_usd": snap.volume_5m_usd,
        "liquidity_usd": snap.liquidity_usd,
        "holder_count": snap.holder_count,
    }


def _build_worker_redis() -> aioredis.Redis:
    """Create a Redis client scoped to one ``fetch_token`` invocation.

    Each Celery task body runs inside its own ``asyncio.run`` loop, so
    we deliberately do *not* share the module-level ``get_redis()``
    singleton here — its pool would bind to the first loop and misbehave
    on subsequent tasks. Tests monkey-patch this factory.
    """
    return aioredis.from_url(str(get_settings().REDIS_URL))


async def _best_effort_publish(
    address: str,
    snap: TokenSnapshot,
    tier: Priority,
) -> None:
    """Write the hot cache and publish a ``price.updated`` event.

    Both writes are wrapped in try/except so a Redis outage never breaks
    the data path — the snapshot has already been committed to Postgres
    by the time we get here.
    """
    payload = _cache_payload(snap, tier)
    payload_for_publish = {**payload, "cache_key": cache_key_for(address)}
    client: aioredis.Redis | None = None
    try:
        client = _build_worker_redis()
    except Exception as exc:
        _log.warning("worker.redis.connect_failed", address=_redact(address), error=str(exc))
        return
    try:
        try:
            await set_price_cache(client, address, payload, ttl_for_tier(tier))
        except Exception as exc:
            _log.warning("worker.cache.failed", address=_redact(address), error=str(exc))
        try:
            await publish_price_updated(client, payload_for_publish)
        except Exception as exc:
            _log.warning(
                "worker.publish.failed",
                address=_redact(address),
                channel=PRICE_UPDATED_CHANNEL,
                error=str(exc),
            )
    finally:
        try:
            await client.aclose()
        except Exception as exc:
            _log.warning("worker.redis.close_failed", address=_redact(address), error=str(exc))


async def _fetch_token_async(token_address: str) -> dict[str, Any]:
    sessionmaker = get_sessionmaker()
    log = _log.bind(token=_redact(token_address))

    try:
        async with _build_source(sessionmaker) as client:
            snap = await client.fetch_one(token_address)
    except PumpFunUnavailableError as exc:
        log.warning("worker.fetch_token.unavailable", error=str(exc))
        return {"address": token_address, "fetched": False, "error": "unavailable"}

    if snap is None:
        log.info("worker.fetch_token.not_found")
        return {"address": token_address, "fetched": False, "reason": "not_found"}

    # Snapshot row is the source of truth: if this raises, the caller
    # sees the error and the cache / pub-sub layer never gets touched.
    async with sessionmaker() as session, session.begin():
        await PriceSnapshotRepository(session).insert(_snapshot_from(snap))
        tier = await _pick_tier_for_token(session, token_address)

    await _best_effort_publish(token_address, snap, tier)

    log.info("worker.fetch_token.done", tier=tier.value)
    return {"address": token_address, "fetched": True, "tier": tier.value}


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
    """Fetch one token → persist snapshot → update cache → publish event."""
    return asyncio.run(_fetch_token_async(token_address))
