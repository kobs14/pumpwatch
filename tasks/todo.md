# Current Session TODO

This file is session-scoped. It is reset at the end of every session with
the next session's name and any carry-over items.

## Active: Session 6 — Alert Engine: Thresholds + Volume Spike

### Carry-over from Session 5

- **Subscribe to `pw:price.updated`** as the alert engine's primary input
  channel. `redis.asyncio` pub-sub is fire-and-forget with zero replay —
  the subscriber must be up *before* any worker publishes, or the event
  is lost. Establish the SUBSCRIBE connection at service startup,
  before Beat fires the first `fetch_batch`. Postgres snapshot rows are
  the source of truth for any replay/backfill need.
- Payload shape per Session 5 contract:
  `{address, ts (ISO8601 UTC), source, tier, cache_key,
    market_cap_usd, price_usd, volume_5m_usd, liquidity_usd,
    holder_count}`. `cache_key` points at `pw:price:<addr>` if the
  consumer needs the cached view over a longer window than a single
  event carries.
- Long-running alert engine should use
  `pumpwatch.cache.redis_client.get_redis()` / `close_redis()` —
  singleton-per-loop is correct for this consumer shape (one service,
  one event loop). Do *not* reach for the worker's
  `_build_worker_redis()` helper; that one is Celery-task-scoped.
- Reuse the Session 5 defensive-outer-try shape for any Telegram /
  Redis write: construct guard + operate guard, both layers, any
  failure only warns. The snapshot row is already committed by the
  time the event arrives.
- At dispatch time (NOT at polling time): read `User.alerts_muted`,
  `quiet_hours_start`, `quiet_hours_end`, and `Subscription.priority`
  (treat `PAUSED` as muted). The worker was deliberately kept
  sub-agnostic (ADR #15); all suppression lives here.
- Implement median + MAD detector per the design in
  `scheduler/priority.py` docstring (statistical, fat-tail-safe).
  Dedup via Redis TTL keys under a fresh `pw:alert:<user>:<token>:<type>`
  namespace — don't reuse `pw:price:*`.
- Persist every alert row to `alerts_sent` *before* dispatching via the
  Telegram bot (CLAUDE.md invariant: no alert sent without being
  persisted first). Reuse `AlertSentRepository`.

### Session 7 carry-over (do not touch this session)

- `price_snapshots` daily partitioning (see Plan notes in the model
  docstring and initial migration).
- Worker dead-letter queue for `PumpFunUnavailableError` after N
  failures, plus Celery retry/backoff once DLQ exists. Session 5
  deliberately picked silent-skip + scheduler re-dispatch to avoid
  scope creep here.
- Prometheus / Grafana for `api_call_log`, Celery queue depths, cache
  hit rate, alert fire/suppress counters.
- Real DexScreener `PriceDataSource` (Pump.fun CF block has been live
  since Session 2; Session 5's factory is ready for it).
- **Compose scheduler `celerybeat-schedule` file-permission bug.** Beat
  crashes on startup with `[Errno 13] Permission denied`. Either pin
  the schedule file to a writable path (volume or `/tmp`) or switch to
  a Redis/DB-backed schedule. Pre-existing Session 4 state; unblocked
  the worker-only smoke during Session 5.
- Consolidate the four TRUNCATE-style sessionmaker fixtures into one
  shared helper (`tests/bot/conftest.py`,
  `tests/integration/test_bot_flow.py`,
  `tests/scheduler/conftest.py`,
  `tests/integration/test_worker_price_ingestion_real_redis.py`).
- Minor: `Redis.aclose()` / `PubSub.aclose()` call sites carry
  `# type: ignore[no-untyped-call]` against the shipped redis-py stubs.
  Drop the ignores once upstream types catch up.

### Future cleanup (still open)

- Remove empty `src/pumpwatch/services/{bot,scheduler,worker,alerts}/`
  placeholders. Session 1 created them; Sessions 3–5 superseded them.
- Per-subscription editing in `/settings` (inline keyboards per token).
- Redis-backed `ConversationHandler` persistence when multi-instance.
