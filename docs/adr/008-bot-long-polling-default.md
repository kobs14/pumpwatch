# ADR 008 — Bot uses long-polling by default; webhook is opt-in

## Context

The Telegram bot service consumes user updates (`/start`, `/add`, etc.)
via either Telegram's long-polling endpoint (`getUpdates`) or a webhook
where Telegram POSTs updates to a public HTTPS URL. Long-polling needs
no public DNS/TLS; webhook needs both but is the productionised shape
recommended by Telegram for any bot that handles real load.

PumpWatch is a single-instance service either way: the `ConversationHandler`
state for `/add`/`/settings` flows lives in-process, so going multi-instance
would require Redis-backed persistence we deliberately deferred. The
question is which transport is the *default* and how the other one is
selected at deploy time.

## Decision

Default to long-polling. Webhook is opt-in via the `BOT_MODE` setting:

- `BOT_MODE=polling` (default) — `Application.run_polling()`. Works with
  zero infrastructure; `docker compose up -d bot` boots cleanly on a
  laptop.
- `BOT_MODE=webhook` — `Application.run_webhook(...)`. Requires
  `BOT_WEBHOOK_URL` (validated by the Settings model_validator) and is
  fronted by a reverse proxy that terminates TLS (Caddy in our deployment
  recipe). Telegram posts to `<BOT_WEBHOOK_URL>/<TELEGRAM_BOT_TOKEN>`;
  the token in the URL path doubles as a secret. An optional
  `BOT_WEBHOOK_SECRET_TOKEN` adds a second IP-spoof defence (Telegram
  echoes it in the `X-Telegram-Bot-Api-Secret-Token` header).

## Consequences

- Local dev stays one-command (`docker compose up -d`) because the
  default is polling. No reverse-proxy or public DNS in the dev story.
- Production deploys flip a single env var. The deployment guide
  (`docs/deployment.md`) walks through Telegram `setWebhook` and the
  Caddyfile snippet.
- The bot remains single-instance regardless of transport. ADR-019
  documents Prometheus exposure separately; the metrics server binds
  before either branch in `bot/main.py:run()`, so the same observability
  surface is available in both modes.
- Switching modes does *not* require a code change — only `.env`. This
  is intentional: it lets a portfolio reader run the bot locally without
  ever paying for HTTPS/DNS.

## Status

Accepted, 2026-04 (Session 3, refined Session 8).
