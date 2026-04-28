# Post-launch backlog

The eight planned sessions are complete. The repo is feature-complete
and deployable per [`docs/deployment.md`](../docs/deployment.md). The
items below are public, optional, and trigger-driven — none of them
block the released system from operating.

## When the trigger fires

- **`price_snapshots` partitioning** — when row count > ~1M.
  Ready-to-run plan: [`docs/migrations/partition-price-snapshots.md`](../docs/migrations/partition-price-snapshots.md).
- **DexScreener batch-mode scheduler refactor** — when observed
  HIGH-tier load saturates DexScreener's ~5 rps. Touches
  `scheduler/tasks.py`, `scheduler/batch.py`, and the `PriceDataSource`
  Protocol.
- **`pumpwatch_cache_hit_ratio` metric** — when a hot-cache *reader*
  exists (e.g., `/list` enriches rows from cache, or the alerts
  subscriber prefers cache over pub-sub payload). The cache is
  currently write-only.
- **Strip `# type: ignore[no-untyped-call]` on `pubsub.aclose()`** —
  attempted in Session 8; redis-py 7.4 stubs still don't type
  `PubSub.aclose()`. Re-attempt when stubs catch up. Sites:
  `src/pumpwatch/alerts/subscriber.py`, `tests/cache/test_redis_client.py`,
  `tests/integration/test_worker_price_ingestion_real_redis.py`,
  `tests/scheduler/test_tasks.py`.
- **Redis-backed `ConversationHandler` persistence** — only needed if
  the bot goes multi-instance. Single-instance polling/webhook is the
  documented shape (ADR-008).

## Open product features

- **Per-subscription editing in `/settings`** (inline keyboards per
  watched token). UI feature, deployment-orthogonal.
- **LLM-driven `/explain` command** — mentioned at design time as a
  possible Session 9; not committed.

## Observations to track in production

- Cloudflare block on Pump.fun's frontend API (Session 2 lessons).
  If it lifts, `PRICE_SOURCE=pumpfun` becomes viable again. Until
  then, `PRICE_SOURCE=dexscreener` is the documented default for
  prod.
- `pumpwatch_alerts_delivery_failed_total` and `pumpwatch_dlq_size`
  should both be near zero in steady state. Spikes on either are
  the operational signal that something upstream is unhealthy.
