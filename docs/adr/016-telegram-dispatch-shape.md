# ADR 016 — Alerts service holds its own `telegram.Bot`

## Context

When an alert fires, the alerts service has to send a Telegram message
to the right chat. The bot service already runs `python-telegram-bot`'s
`Application` with the same token (for `getUpdates`/long-polling or
webhook receipt). Three patterns were on the table:

1. Refactor `bot/` into a shared library; alerts imports it.
2. Push outbound messages onto a Redis "outbox" list; the bot service
   drains and sends.
3. The alerts service constructs its own standalone `telegram.Bot`
   client against the same token.

(1) collapses two services into a single-process bottleneck for a
horizontally scalable concern. (2) adds a hop for every alert and a new
Redis namespace (against [ADR-013](013-redis-roles.md)). (3) needs a
careful read of Telegram's rate-limit and conflict semantics.

## Decision

Pattern (3): the alerts service builds its own `telegram.Bot(token=...)`
at startup (`alerts/dispatcher.py:build_dispatcher`), keeps it for the
lifetime of the service, and uses it only for `send_message`. The bot
service is the *only* process calling `getUpdates`. Two processes
sharing the token is safe because Telegram serializes only Update
*consumption* per token; outbound HTTP is rate-limited only by the
documented per-chat (1/sec) and global (~30/sec) limits, which we
enforce with one `aiolimiter` per layer.

## Consequences

- Alerts is independently scalable (subject to ADR-008's "single-
  instance" caveat for `ConversationHandler`, which doesn't apply here
  because the dispatcher is stateless beyond the rate limiters).
- The dispatcher is a thin class around the Bot client: one inline
  retry on `TelegramError`, then mark the (already persisted) row's
  `delivery_error` and move on. Reconciliation handles persistent
  failures separately (`alerts/reconciler.py`).
- If we ever add webhook mode for the bot (see ADR-008), nothing on
  the dispatch side changes — it never calls `getUpdates`.

## Status

Accepted, 2026-04 (Session 6).
