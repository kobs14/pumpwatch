# Current Session TODO

This file is session-scoped. It is reset at the end of every session with
the next session's name and any carry-over items.

## Active: Session 7 — Hardening: Observability, Error Handling, Scale

### Carry-over from Session 6

- `delivery_error` reconciliation. Session 6 picked one in-line retry +
  mark-failed; persistent failures sit on `alerts_sent` rows with
  `delivered=False`. A periodic Celery task should sweep recent failures
  and re-dispatch (small Beat entry, idempotent against the dedup key).
- Per-event N+1 user load. The subscriber currently does one
  `SELECT users WHERE id IN (...)` per event after `get_active_by_token`.
  Profile under load; if it shows up, lift to a join on the
  `SubscriptionRepository.get_active_by_token` projection.

### Session 7 carry-over (do not touch out of scope)

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
- Consolidate the now-five truncate-style sessionmaker fixtures into
  one shared helper (`tests/bot/conftest.py`,
  `tests/integration/test_bot_flow.py`,
  `tests/scheduler/conftest.py`,
  `tests/integration/test_worker_price_ingestion_real_redis.py`,
  `tests/alerts/conftest.py` + `tests/integration/test_alerts_real_redis.py`).
- Minor: `Redis.aclose()` / `PubSub.aclose()` call sites carry
  `# type: ignore[no-untyped-call]` against the shipped redis-py stubs.
  Drop the ignores once upstream types catch up.

### Future cleanup (still open)

- Remove empty `src/pumpwatch/services/{bot,scheduler,worker,alerts}/`
  placeholders. Session 1 created them; Sessions 3–6 superseded them
  (real packages live one level up at `src/pumpwatch/{bot,scheduler,
  cache,alerts}/`).
- Per-subscription editing in `/settings` (inline keyboards per token).
- Redis-backed `ConversationHandler` persistence when multi-instance.
