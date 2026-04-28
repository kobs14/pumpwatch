# ADR 017 — Suppress but still persist; still mark fired

## Context

Some alerts shouldn't reach the user: the user has muted alerts, the
subscription is `PAUSED`, or the wall-clock time is inside the user's
quiet-hours window. The naive design is to skip those alerts entirely
— don't persist, don't dedup, don't dispatch.

This is wrong. Two failure modes follow:

1. **Audit gap.** A user who reports "I should have been alerted at
   3am — was I muted?" can't be answered without a record.
2. **Thundering herd on unmute.** If a user mutes alerts during a
   24-hour drawdown event and unmutes the next morning, every
   threshold breach that occurred during the window would be eligible
   to fire on the next price tick. The user gets carpet-bombed.

## Decision

Suppressed alerts hit `alerts_sent` with `delivered=False` and
`delivery_error="suppressed: <reason>"` (e.g., `suppressed: muted`,
`suppressed: paused`, `suppressed: quiet_hours`). The Redis dedup TTL
key under `pw:alert:<user>:<token>:<type>` is set just like a
delivered alert.

The reconciler (`alerts/tasks.py:reconcile_failed`) skips any row
whose `delivery_error` starts with `"suppressed:"`. Suppression is
*not* a transient delivery failure to retry. The reconciler only
re-attempts genuinely failed dispatches (e.g., a transient
`TelegramError`).

Dedup TTL cooldowns by type:

- `*_HIT` = 1 hour (milestones — rare, costly to re-fire).
- `*_WARNING` = 5 minutes (heads-up — re-arm fast).
- `VOLUME_SPIKE` = 10 minutes (between the two).

## Consequences

- The audit trail is complete. `SELECT * FROM alerts_sent WHERE
  delivery_error LIKE 'suppressed:%'` answers "what did the user
  miss?" exactly.
- Unmute does not replay history. The dedup keys set during the muted
  window mean the next price tick can't re-fire the same alert until
  its cooldown expires.
- The reconciler's "skip suppressed" rule is load-bearing — without
  it, every periodic Beat sweep would re-attempt every suppressed
  row. This is enforced by the `delivery_error NOT LIKE 'suppressed:%'`
  filter in `AlertRepository.list_recently_failed`.
- "Did the user actually receive it?" is reconstructible from
  `delivered`. We deliberately favour audit completeness over a
  delivered-only `alerts_sent`.

## Status

Accepted, 2026-04 (Session 6).
