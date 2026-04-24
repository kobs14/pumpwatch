"""Unit tests for the hot-cache + pub-sub helpers via fakeredis.

fakeredis' ``FakeAsyncRedis`` speaks the subset of the redis-py
``asyncio.Redis`` API we exercise here (SET with EX, GET, PUBLISH /
SUBSCRIBE). No real broker or daemon involved.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import fakeredis
import redis.asyncio as aioredis

from pumpwatch.cache.redis_client import (
    PRICE_UPDATED_CHANNEL,
    cache_key_for,
    publish_price_updated,
    set_price_cache,
    ttl_for_tier,
)
from pumpwatch.db.enums import Priority


def _fake() -> aioredis.Redis:
    """Return a fresh fakeredis async client.

    ``FakeAsyncRedis`` implements the same interface shape as
    ``redis.asyncio.Redis``; we ``cast`` so mypy sees the production
    type at call sites without us pulling fakeredis into ``src``.
    """
    return cast(aioredis.Redis, fakeredis.FakeAsyncRedis())


async def test_set_price_cache_stores_json_with_ttl() -> None:
    client = _fake()
    payload = {
        "address": "tokABC",
        "ts": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        "market_cap_usd": Decimal("1234.56"),
        "price_usd": None,
        "tier": "high",
    }

    await set_price_cache(client, "tokABC", payload, ttl_seconds=60)

    raw = await client.get(cache_key_for("tokABC"))
    assert raw is not None
    decoded = json.loads(raw)
    assert decoded["address"] == "tokABC"
    assert decoded["ts"] == "2026-04-24T12:00:00+00:00"
    assert decoded["market_cap_usd"] == "1234.56"  # Decimal → string
    assert decoded["price_usd"] is None
    assert decoded["tier"] == "high"

    ttl = await client.ttl(cache_key_for("tokABC"))
    assert 0 < ttl <= 60


async def test_publish_price_updated_reaches_a_subscriber() -> None:
    pub = _fake()
    sub = _fake()

    pubsub = sub.pubsub()
    await pubsub.subscribe(PRICE_UPDATED_CHANNEL)

    # Drain the 'subscribe' confirmation so the next get_message is the payload.
    for _ in range(5):
        confirm = await pubsub.get_message(ignore_subscribe_messages=False, timeout=0.1)
        if confirm and confirm.get("type") == "subscribe":
            break

    # fakeredis pub-sub channels are isolated per-instance. To verify the
    # encoding path end-to-end we publish and receive on the same instance.
    pubsub_same = pub.pubsub()
    await pubsub_same.subscribe(PRICE_UPDATED_CHANNEL)
    for _ in range(5):
        confirm = await pubsub_same.get_message(ignore_subscribe_messages=False, timeout=0.1)
        if confirm and confirm.get("type") == "subscribe":
            break

    subscribers = await publish_price_updated(
        pub,
        {"address": "tokXYZ", "tier": "medium", "ts": datetime(2026, 4, 24, tzinfo=UTC)},
    )
    assert subscribers >= 1

    for _ in range(20):
        msg = await pubsub_same.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is not None:
            break
        await asyncio.sleep(0.01)
    assert msg is not None, "expected to receive a published message"
    assert msg["channel"].decode() == PRICE_UPDATED_CHANNEL
    payload = json.loads(msg["data"])
    assert payload["address"] == "tokXYZ"
    assert payload["tier"] == "medium"

    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await pubsub_same.aclose()  # type: ignore[no-untyped-call]


async def test_ttl_for_tier_returns_expected_defaults() -> None:
    # Settings defaults from config.py; a change there should force this
    # test to update too.
    assert ttl_for_tier(Priority.HIGH) == 60
    assert ttl_for_tier(Priority.MEDIUM) == 300
    assert ttl_for_tier(Priority.LOW) == 900
    # PAUSED gets the LOW TTL fallback — the worker writes snapshots
    # regardless of mute state; alert dispatch is Session 6's call.
    assert ttl_for_tier(Priority.PAUSED) == 900
