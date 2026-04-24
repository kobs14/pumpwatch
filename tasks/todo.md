# Current Session TODO

This file is session-scoped. It is reset at the end of every session with
the next session's name and any carry-over items.

## Active: Session 5 — Worker Pool & Price Ingestion

### Carry-over notes from Session 4

- `fetch_token` is a thin shell this session. Session 5 must:
  - Persist every returned `TokenSnapshot` as a `PriceSnapshot` row.
  - Push a "latest" snapshot to a Redis hot cache (key scheme TBD).
  - Publish a `price.updated` pub-sub event for the Session 6 alert engine
    to consume.
- DexScreener fallback for Pump.fun's CF block is still unbuilt. Session 5
  should decide between (a) browser-like UA / cookie plumbing and (b)
  adding a `DexScreenerClient : PriceDataSource` implementation.
- The `fetch_token` task currently logs per logical call via the wired-in
  `ApiCallLogRepository`. Session 5's expanded body should re-use the same
  sessionmaker hand-off for its snapshot writes (don't spin up a second
  engine).
- Subscription priority is now computed and persisted per-tick by the
  scheduler. Session 5 workers can trust `Subscription.priority` as the
  source of truth for tier when they need it.
- Queue routing (`default`, `high`, `medium`, `low`) is wired in the
  worker compose service via `-Q default,high,medium,low`. Session 7
  should split into separate worker pools if tier isolation becomes
  desirable.
- Celery result backend uses Redis with a 1-hour TTL. If Session 5 starts
  storing larger result payloads, revisit `result_expires` or switch to a
  smaller ad-hoc payload.

### Session 6 carry-over

- Alert engine reads `User.alerts_muted` and `quiet_hours_*` before
  dispatch. Polling continues even for muted users (so data is hot when
  they unmute); skipping happens at dispatch time.
- Median+MAD volume-spike detection is Session 6's job, not the
  scheduler's. The priority module docstring notes this explicitly.

### Future cleanup (not Session 5 scope)

- Remove empty `src/pumpwatch/services/{bot,scheduler,worker,alerts}/`
  placeholders. Session 1 created them; Sessions 3–4 superseded them.
- Per-subscription editing in `/settings` (inline keyboards per token).
- Redis-backed `ConversationHandler` persistence when multi-instance.
- Unify the `tests/bot/conftest.py`, `tests/integration/test_bot_flow.py`,
  and new `tests/scheduler/conftest.py` truncate fixtures.
