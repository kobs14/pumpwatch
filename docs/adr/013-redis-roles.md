# ADR 013 — Single Redis instance, four roles

## Context

PumpWatch needs Redis for several distinct things: the Celery broker,
the Celery result backend, a hot price cache the worker writes after
every snapshot, and a pub-sub channel the alerts service consumes. A
proliferation of Redis instances (or a per-role logical-DB split) would
be operationally noisier without buying anything for our scale.

CLAUDE.md states "Postgres is the source of truth. Redis is *only* a
cache, broker, and pub-sub bus." That sets a hard ceiling on Redis's
role count; this ADR pins which exact roles count.

## Decision

A single Redis 7 instance. Four roles, all on the same database:

1. **Celery broker** — task queues `default`, `high`, `medium`, `low`.
2. **Celery result backend** — task results (we mostly fire-and-forget,
   but Celery wants a backend configured).
3. **Hot price cache** — keys `pw:price:<addr>` storing flat JSON,
   tier-varying TTL (HIGH=60s, MEDIUM=300s, LOW=900s). Best-effort
   write from the worker; Postgres is authoritative.
4. **Pub-sub** — single global channel `pw:price.updated`. Payload is
   `{address, ts, source, tier, cache_key}`. Alerts subscribers filter
   in-process; no per-token channel sharding.

A fifth Redis namespace exists in code but is part of the *cache* role:
`pw:alert:<user>:<token>:<type>` TTL keys for alert dedup. These ride
the same role boundary because dedup is a TTL-bounded best-effort
mechanism, exactly like the price cache. ADR-017 covers the dedup
semantics.

## Decision boundary

No further Redis roles without an ADR. Specifically: when Session 7
needed a dead-letter queue for persistent worker failures, we wrote it
to a Postgres table (see [ADR-018](018-dlq-postgres-not-redis.md))
rather than introducing a fifth Redis namespace.

## Consequences

- Redis can fail (or be wiped) and the system continues to function:
  Celery reconnects on restart; the cache repopulates on the next poll;
  pub-sub messages in flight are lost, but Postgres snapshots are not.
  This matches the CLAUDE.md invariant "anything in Redis must be
  reconstructible from Postgres."
- All Redis keys use the `pw:` prefix to namespace against any
  shared-Redis story we might fall into later.
- The hot cache is currently *write-only*. A reader (e.g., `/list`
  enriching from cache) is open work; when it lands, a
  `pumpwatch_cache_hit_ratio` metric becomes useful.

## Status

Accepted, 2026-04 (Session 5).
