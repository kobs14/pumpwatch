---
name: verify
description: Run the PumpWatch verification checklist (ruff format, ruff check, mypy strict, pytest, forbidden-pattern scan). Use at the end of an implementation phase, before /post-session and before any commit. Reports per-step pass/fail; does not auto-fix.
---

# Verification checklist

Encodes CLAUDE.md §Code Conventions + §Forbidden Patterns. Runs the same gates the project's pre-commit + CI use.

## Steps

Run each step in order. Report the result of each step before moving on. If a step fails, **stop** and surface the error verbatim — do not auto-fix unless the user asks.

1. **ruff format check** (no rewrite, just verify formatting):
   ```bash
   uv run ruff format --check src tests
   ```

2. **ruff lint:**
   ```bash
   uv run ruff check src tests
   ```

3. **mypy strict on src AND tests:**
   ```bash
   uv run mypy --strict src tests
   ```
   Note: `pyproject.toml` defaults `files = ["src"]`; the explicit `src tests` invocation is mandatory because tests have their own type errors that strict mode catches.

4. **Test suite (gated integration tests skip by default):**
   ```bash
   uv run pytest -q
   ```
   - Integration tests under `tests/integration/` are gated and skip without `RUN_INTEGRATION=1` + a real Redis/Postgres reachable.
   - To run them: `RUN_INTEGRATION=1 uv run pytest -q tests/integration/`

5. **Forbidden-pattern scan** (catches what mypy/ruff don't):
   ```bash
   # print() outside scripts/
   rg -n 'print\(' src/ tests/
   # time.sleep inside async (multi-line context)
   rg -n -B 2 'time\.sleep' src/
   # sync HTTP
   rg -n '^import requests|^from requests' src/ tests/
   # bare except / Exception without re-raise
   rg -n 'except:|except Exception:' src/
   # asyncio.run outside main.py / scripts
   rg -n 'asyncio\.run\(' src/ | rg -v '/main\.py:|^scripts/'
   ```
   Treat any non-empty output as a failure unless the line is clearly intentional (e.g., `print` inside `scripts/`, `asyncio.run` inside a `main.py` entry point).

6. **Migration head check** (only if `alembic/versions/` changed since last commit):
   ```bash
   uv run alembic heads
   ```
   Must report exactly one head. Multiple heads = a merge migration was missed.

## Output shape

```
## Verification: <PASS | FAIL>

- ruff format:   ✅
- ruff check:    ✅
- mypy strict:   ✅
- pytest:        ✅  (NN passed, NN skipped)
- forbidden:     ✅  (no hits)
- alembic heads: ✅  (single head: <revision>)
```

If any step fails, print the failing tool's output verbatim under that step's line and stop. Do not proceed to `/post-session`.
