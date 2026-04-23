# Lessons Learned

This file accumulates surprises, gotchas, and design lessons across all
sessions. Append-only. Each entry should help a future session avoid a
mistake or make a better choice.

## Format

```
## Session N — YYYY-MM-DD
- **Lesson:** One-sentence summary of what was learned.
  **Context:** What we were doing when it came up.
  **Action:** What we changed (or should change) as a result.
```

---

## Session 1 — 2026-04-22

- **Lesson:** uv resolves the latest Python (3.14) by default when `requires-python = ">=3.12"` is set.
  **Context:** `uv lock` and `uv sync` picked Python 3.14 instead of 3.12.
  **Action:** Use `--python 3.12` flag for local commands and `UV_PYTHON_PREFERENCE=only-system` in the Dockerfile to use the base image's Python.

- **Lesson:** The hatchling build backend module is `hatchling.build`, not `hatchling.backends`.
  **Context:** `uv sync` failed with `ModuleNotFoundError: No module named 'hatchling.backends'`.
  **Action:** Fixed `build-backend` in pyproject.toml to `"hatchling.build"`.

- **Lesson:** `tool.uv.dev-dependencies` is deprecated in favor of `dependency-groups.dev`.
  **Context:** `uv lock` emitted a deprecation warning.
  **Action:** Switched to `[dependency-groups]` section in pyproject.toml.

- **Lesson:** ruff's top-level `select` is deprecated — use `[tool.ruff.lint]` section.
  **Context:** `ruff check` warned about deprecated config.
  **Action:** Moved `select` under `[tool.ruff.lint]`.

- **Lesson:** Bootstrap files (`todo.md`, `lessons.md`) were created in the project root instead of `tasks/` directory; `.gitignore` was missing.
  **Context:** Session prompt expected them at `tasks/todo.md` etc.
  **Action:** Created `tasks/` directory and moved files. Created `.gitignore`.

## Session 2 — 2026-04-23

- **Lesson:** Pump.fun's frontend API is blocked at Cloudflare (HTTP 530 "Origin Down") for unauthenticated external clients as of 2026-04-23.
  **Context:** The end-of-session live smoke test against two well-known Solana mints (Bonk, RAY) both returned 530 with a Cloudflare interstitial HTML page. Tenacity correctly retried, then the client raised `PumpFunUnavailableError` as designed.
  **Action:** Session 2 ships the client contract, retries, rate limiter, and parser — all proven via `aioresponses` mocks. The `PriceDataSource` abstraction means Session 5 can swap to DexScreener (or add a browser-like User-Agent / bypass) without touching repos. Do **not** invent alternate endpoints in a future session without first checking whether the upstream block has lifted.

- **Lesson:** Alembic autogenerate correctly captured every `CheckConstraint`, `UniqueConstraint`, compound `Index`, and FK `ondelete` on first pass — no hand-editing required beyond adding a planning comment and wrapping one long CHECK constraint line.
  **Context:** Contrary to the session prompt's warning, autogenerate did not miss CHECKs/indexes in SA 2.x + alembic 1.13 against a Postgres 16 target. Server-side defaults on columns were only picked up after I explicitly set `server_default=...` on the `mapped_column(...)` — a Python `default=...` alone is not autogen-visible.
  **Action:** For every future column that needs a non-null default, set **both** `default=` (ORM-side) and `server_default=` (DDL-side). Do not rely on autogenerate to infer server defaults from Python defaults.

- **Lesson:** `asyncio.run()` inside `alembic/env.py` conflicts with a pytest-asyncio event loop if you call `alembic.command.upgrade()` directly from an async fixture.
  **Context:** The `_test_database` fixture failed with `RuntimeError: asyncio.run() cannot be called from a running event loop` when running migrations.
  **Action:** Wrap the alembic call in `await asyncio.to_thread(_run_migrations, url)` so alembic spawns its own loop in a worker thread. Cleaner than refactoring `env.py`, which is shared with the CLI path.

- **Lesson:** `AsyncSession.expire()` and `.expire_all()` are **sync** methods; `.refresh()` is async.
  **Context:** Two repo tests failed with `TypeError: object NoneType can't be used in 'await' expression` after I naively awaited `.expire()`. Pure ORM-state operations never touch the DB, so they don't need to be async. `.refresh()` reloads from the DB, so it does.
  **Action:** Use `await session.refresh(obj)` after an UPDATE statement when you need to see the new values through the ORM. Never `await session.expire(...)`.

- **Lesson:** `ApiCallLogRepository` is implemented in Session 2 but **not wired into `PumpFunClient`**.
  **Context:** The session prompt mentions logging API calls "via the repository (you'll need to pass a session factory in — design for this)". Wiring it in this session would require inventing a session-factory hand-off before the scheduler/worker (Sessions 4–5) owns the session lifecycle.
  **Action:** The repo exists and is covered by tests; Session 4/5 will wire it up when the scheduler owns an `async_sessionmaker` callable and can pass it into the client.

- **Lesson:** Test conftest must set required env vars via `os.environ.setdefault` **before** any pumpwatch import, and defensively call `get_settings.cache_clear()` afterwards.
  **Context:** `pumpwatch.db.session` creates the engine eagerly at import time via `_settings = get_settings()`. If conftest imports pumpwatch before setting `DATABASE_URL`, the module-level engine binds to the wrong DB. This is known-technical-debt in `session.py` (Session 1 carry-over) — Session 2 worked around it rather than refactoring.
  **Action:** Keep `tests/__init__.py` empty. The top of `tests/conftest.py` sets envs, imports pumpwatch second, and constructs its own test engine (`NullPool`) that tests use — the module-level engine is never exercised in tests.
