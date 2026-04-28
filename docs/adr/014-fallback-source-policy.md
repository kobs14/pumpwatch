# ADR 014 — Fallback-source policy via `PriceDataSource` factory

## Context

Pump.fun's frontend API has been Cloudflare-blocked for unauthenticated
external clients (Session 2 lessons.md, 2026-04-23). Treating the data
source as fixed would couple the worker to one upstream that has
demonstrably gone dark before. We need a substitution seam that lets
deployments swap sources without code changes, and tests bypass the
network entirely.

CLAUDE.md captures this as an architectural invariant: "All external
APIs sit behind an interface."

## Decision

The `PriceDataSource` Protocol in `src/pumpwatch/sources/base.py`
defines four async methods (`fetch_one`, `fetch_batch`, `close`,
context-manager protocol). Concrete implementations:

- `PumpFunClient` (Session 2) — primary.
- `FakePriceDataSource` — dev-only / tests.
- `DexScreenerClient` (Session 7) — see [ADR-020](020-dexscreener-as-fallback.md).

The factory `build_source(sessionmaker)` in
`src/pumpwatch/sources/factory.py` reads `Settings.PRICE_SOURCE` and
returns the right implementation. Selectable values:
`pumpfun` (default), `dexscreener`, `fake`. Tests monkey-patch
`scheduler/tasks._build_source` directly rather than flipping the
setting, which keeps the factory itself unit-testable in isolation.

## Consequences

- Adding a new source is one branch in `build_source` plus one new
  module that satisfies the Protocol. No worker, scheduler, alerts,
  or repo changes needed.
- The Protocol surface is intentionally small — no batch retries, no
  caching, no pagination. Each implementation owns its own retry
  (tenacity), its own rate limiter (aiolimiter), and its own observability
  hook (the `api_call_log` write inside `fetch_one`/`fetch_batch`).
- Domain exceptions share a parent (`SourceUnavailableError`), so the
  scheduler's retry/DLQ branch catches one symbol regardless of which
  source raised. See `src/pumpwatch/sources/exceptions.py`.

## Status

Accepted, 2026-04 (Session 5; DexScreener concrete implementation
landed Session 7).
