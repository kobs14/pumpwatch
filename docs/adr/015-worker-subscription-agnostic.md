# ADR 015 — Worker is subscription-agnostic

## Context

The `fetch_token` Celery task fetches one token from the configured
`PriceDataSource` and persists the result. It runs once per token per
priority-tier interval. The question is how much subscription state
(thresholds, mute flags, quiet hours, paused-ness) the worker needs
to consult while doing this.

A subscription-aware worker would have to:

- Filter writes based on whether any active sub watches the token.
- Read `User.alerts_muted` and `Subscription.priority == PAUSED` to
  decide whether to publish the pub-sub event.
- Re-resolve quiet-hours per user — for *every* event — to decide
  whether to publish.

That couples the polling layer to alerting policy and forces every
worker invocation to do a series of joins.

## Decision

The worker writes a `PriceSnapshot` row + hot cache entry + pub-sub
event **unconditionally** when the source returns data. It reads
`Subscription.priority` only to derive the cache TTL and the event's
`tier` field. All user-mute, quiet-hours, and `PAUSED` suppression
lives at alert-dispatch time in `alerts/suppression.py` — see
[ADR-017](017-suppress-but-still-persist.md).

## Consequences

- Workers are stateless beyond settings. A worker pod can be killed
  and restarted at any time without losing or corrupting alert state.
- One pub-sub event per token per poll regardless of subscriber count.
  The alerts service iterates subscribers in-process; not every event
  produces a Telegram message.
- Adding a new alert detector (e.g., liquidity drop) doesn't touch the
  worker. The detector consumes the same `pw:price.updated` channel.
- The worker's three steps are ordered: persist (Postgres) → cache
  (Redis SET) → publish (Redis PUBLISH). Steps 2 and 3 are
  best-effort: a Redis outage logs a warning but doesn't break step 1.
  Persistence is the contract; the rest is acceleration.

## Status

Accepted, 2026-04 (Session 5).
