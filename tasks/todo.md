# Current Session TODO

This file is session-scoped. It is reset at the end of every session with
the next session's name and any carry-over items.

## Active: Session 8 — Documentation, README, Deployment Guide

### Carry-over from Session 7

- `price_snapshots` daily partitioning. Model docstring still says
  "once row count exceeds ~10M". Empty pre-deploy; do this as a
  one-revision online migration (declarative `RANGE(ts)`, parent + N
  children, Beat task creates tomorrow's child at midnight) when
  volume warrants.
- DexScreener batch-mode scheduler refactor. Session 7 ships
  per-token `fetch_token` against DexScreener's comma-list endpoint
  (each call hits `/latest/dex/tokens/{single_addr}`). Real batching
  would dispatch one Celery task per (priority, batch) instead of
  per token. Touches `scheduler/tasks.py`, `scheduler/batch.py`,
  and the `PriceDataSource` Protocol. Worth doing only if observed
  HIGH-tier load actually saturates DexScreener's ~5 rps.
- `pumpwatch_cache_hit_ratio` metric. Deferred from Session 7 — the
  hot cache (`pw:price:<addr>`) is currently write-only. Add the
  metric when a reader exists (e.g., `/list` enriches rows from
  cache, or the alerts subscriber prefers cache over pub-sub
  payload).
- Webhook deployment for the bot. Long-polling is fine for dev /
  single-instance; webhook is the productionised shape for Session 8.
- ADR formalisation in `docs/adr/`. ADRs #13–#21 currently live
  inline in `PROJECT_STATUS.md`; the deployment guide should split
  them into per-decision files with context / decision / consequences.
- Architecture diagrams (Mermaid in README): the five-service shape,
  the pub-sub flow, the Beat schedule.
- Drop the `# type: ignore[no-untyped-call]` on `pubsub.aclose()`
  once redis-py stubs catch up. (`Redis.aclose()` already typed.)

### Future cleanup (still open)

- Remove empty `src/pumpwatch/services/{bot,scheduler,worker,alerts}/`
  placeholders. Session 1 created them; Sessions 3–7 superseded them
  (real packages live one level up at `src/pumpwatch/{bot,scheduler,
  cache,alerts,observability}/`).
- Per-subscription editing in `/settings` (inline keyboards per token).
- Redis-backed `ConversationHandler` persistence when multi-instance.
