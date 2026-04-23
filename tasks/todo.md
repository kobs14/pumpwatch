# Current Session TODO

This file is session-scoped. It is reset at the end of every session with
the next session's name and any carry-over items.

## Active: Session 2 — Data Layer & Pump.fun Client

See the Session 2 prompt provided by the user for the full scoped steps.

### Carry-over notes from Session 1
- Session 2 must add `aiohttp`, `tenacity`, `aiolimiter` to pyproject.toml
- Python 3.12 is the locked version (uv resolves 3.14 by default — use
  `--python 3.12` or the `UV_PYTHON_PREFERENCE=only-system` env in Docker)
- `db/session.py` creates the engine at module import time via `get_settings()`,
  which requires env vars to be set. Be mindful of this when importing in tests.
- Alembic async env is configured and tested — ready for first migration
