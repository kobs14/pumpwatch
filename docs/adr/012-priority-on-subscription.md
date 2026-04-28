# ADR 012 — Priority lives on `Subscription`, not `Token`

## Context

The scheduler computes a priority tier (HIGH / MEDIUM / LOW) for each
watched token to decide how often to poll it. Tier depends on distance
to either the growth or stoploss threshold, recent volatility, and
recent volume — all of which are *per-user* numbers because each user
sets their own thresholds.

Two models could carry the tier:

- A column on `Token` (one tier per token, regardless of which user
  watches it).
- A column on `Subscription` (one tier per user-token pair).

The Session 2 schema already had `Subscription.priority` and a
`Priority` enum. The question was whether to *also* add a token-level
tier or to reuse what was there.

## Decision

Reuse `Subscription.priority` as the only source of tier truth. The
batch builder in `scheduler/batch.py` groups subs by token and picks
`max(priority)` across the subscribers to drive Celery queue routing
(`high`/`medium`/`low`). No `Token.priority_tier` column is added.

Per-subscription priorities are recomputed in bulk on every Beat tick
via `SubscriptionRepository.set_priorities`, after the priority module
(`scheduler/priority.py`) takes the current state of each subscription
and produces a new tier.

## Consequences

- Single source of truth. Adding a `Token.priority_tier` would require
  picking a tie-breaker rule on every Beat tick to reconcile per-sub
  tiers into one token tier — extra state for no benefit.
- The batch builder doesn't need a join into `tokens` to know what
  queue to dispatch on; it has the priority on the subscription row
  directly.
- A token watched by both a HIGH-tier and a LOW-tier subscriber polls
  at HIGH cadence. Both subscribers see the data; only the HIGH-tier
  one triggers the polling cost. This is the right shape — a token
  isn't free to skip just because *one* of its watchers wouldn't
  notice.

## Status

Accepted, 2026-04 (Session 4).
