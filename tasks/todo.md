# Current Session TODO

This file is session-scoped. It is reset at the end of every session with
the next session's name and any carry-over items.

## Active: Session 3 — Telegram Bot, Commands, User Onboarding

See the Session 3 prompt provided by the user for the full scoped steps.

### Carry-over notes from Session 2

- Session 3 must add `python-telegram-bot[ext]>=21` to `pyproject.toml`
  (then `uv lock --python 3.12 && uv sync --python 3.12`).
- `TELEGRAM_BOT_TOKEN` is already declared in `Settings` and documented in
  `.env.example`. The bot code should read it via `get_settings()`.
- The `UserRepository.upsert_from_telegram` and
  `SubscriptionRepository` methods are ready — wire `/add`, `/list`,
  `/stop`, `/settings` through these repos. **Do not** add SQL in handlers.
- `db/session.py` still creates its engine eagerly at module import. The
  bot service should import it lazily (inside handler setup) so that a
  missing env var in CI/test fails loudly in one clear place.
- Pump.fun API is currently Cloudflare-blocked (HTTP 530). Session 3
  doesn't touch the data source, but keep this in mind when writing any
  end-to-end "paste an address and see a price" demo — use the fake source
  for demos until Session 5 addresses the block.
- `ApiCallLogRepository` exists but is not wired into `PumpFunClient` yet.
  Not Session 3's problem — mentioned here for continuity.
- Telegram rate limits (`TELEGRAM_PER_CHAT_MSG_PER_SEC`,
  `TELEGRAM_GLOBAL_MSG_PER_SEC`) are already in `Settings`. The outbound
  rate limiter lives in Session 6 (alert engine), not Session 3 — command
  handlers reply inline and don't need a dedicated limiter.
