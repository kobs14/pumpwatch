# Architecture Decision Records

Each file in this directory captures a single non-trivial architectural
decision in PumpWatch. Format follows CLAUDE.md: **Context / Decision /
Consequences**.

ADRs are append-only. To revisit a decision, write a new ADR that
supersedes the old one and update the old ADR's status to "Superseded by
ADR-NNN". Never edit a decision in place.

A handful of one-line decisions (numbered #1–#7, #11, #21 in the project
history) live inline in [`PROJECT_STATUS.md`](../../PROJECT_STATUS.md)
as a quick-reference table because they were too short to warrant a file.

## Index

| #   | Title                                                                                | Decided  |
|-----|--------------------------------------------------------------------------------------|----------|
| 008 | [Bot uses long-polling by default; webhook is opt-in](008-bot-long-polling-default.md) | Session 3 |
| 012 | [Priority lives on `Subscription`, not `Token`](012-priority-on-subscription.md)     | Session 4 |
| 013 | [Single Redis instance, four roles](013-redis-roles.md)                              | Session 5 |
| 014 | [Fallback-source policy via `PriceDataSource` factory](014-fallback-source-policy.md)| Session 5 |
| 015 | [Worker is subscription-agnostic](015-worker-subscription-agnostic.md)               | Session 5 |
| 016 | [Alerts service holds its own `telegram.Bot`](016-telegram-dispatch-shape.md)        | Session 6 |
| 017 | [Suppress but still persist; still mark fired](017-suppress-but-still-persist.md)    | Session 6 |
| 018 | [DLQ is a Postgres table, not a fifth Redis namespace](018-dlq-postgres-not-redis.md)| Session 7 |
| 019 | [Per-service Prometheus `/metrics` endpoints](019-prometheus-per-service.md)         | Session 7 |
| 020 | [DexScreener as the ADR-014 fallback source](020-dexscreener-as-fallback.md)         | Session 7 |
