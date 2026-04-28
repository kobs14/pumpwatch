# ADR 020 — DexScreener as the ADR-014 fallback source

## Context

Pump.fun's frontend API has been Cloudflare-blocked since
Session 2 (lessons.md, 2026-04-23). [ADR-014](014-fallback-source-policy.md)
defined the `PriceDataSource` Protocol and the `build_source()` factory
for swapping data sources, but only `PumpFunClient` and
`FakePriceDataSource` shipped in Session 5. Session 7 needed a real
fallback to land before the deployment guide.

DexScreener's `/latest/dex/tokens/{addresses}` returns recent pair data
for one or more comma-separated mint addresses, including price,
liquidity, volume, and 5m/1h/24h windows. The endpoint covers Solana
(and every other major chain), so the upstream block doesn't apply.

Two concrete decisions had to be made: how to select pairs from a
multi-pair response, and whether to keep the per-token `fetch_token`
shape or refactor to true batch dispatch.

## Decision

`DexScreenerClient` implements the full `PriceDataSource` Protocol —
`fetch_one`, `fetch_batch`, tenacity retry, `api_call_log` writes,
context manager, `close()`. Selectable via `PRICE_SOURCE=dexscreener`.

**Pair selection** when a single address returns multiple pairs (e.g.,
Raydium + Orca):

1. Filter to `chainId == "solana"` AND `baseToken.address == requested_address`.
2. From the filtered set, pick the pair with the highest `liquidity.usd`.

Order in the response is not guaranteed; one address can produce many
pairs. The "highest liquidity Solana pair" rule is documented in
`tasks/lessons.md` Session 7.

**Per-token vs batch dispatch.** The scheduler still dispatches one
`fetch_token` per token even on `PRICE_SOURCE=dexscreener`. Real
batching (one Celery task per (priority, batch) chunk) would touch
`scheduler/tasks.py`, `scheduler/batch.py`, and the Protocol surface.
Worth doing only if observed HIGH-tier load saturates DexScreener's
~5 rps published limit; until then the per-token shape stays inside
that limit via the client's `aiolimiter`. Refactor is on the
public TODO.

`DexScreenerUnavailableError` shares a parent
(`SourceUnavailableError`) with `PumpFunUnavailableError`, so the
scheduler's retry/DLQ branch in
[ADR-018](018-dlq-postgres-not-redis.md) catches one symbol regardless
of which source is configured.

## Consequences

- Cutover is one env var: `PRICE_SOURCE=dexscreener`. No code changes,
  no migrations.
- `holder_count` is `None` from DexScreener (the API doesn't expose it).
  Pump.fun does, when reachable. Detector logic accepts `None` already.
- The `api_call_log` writes preserve the source label, so observability
  shows which source produced which request.
- No upper bound on DexScreener stability; if it goes dark too, the
  Protocol seam means a third source is one more `elif` in
  `build_source()`.

## Status

Accepted, 2026-04 (Session 7).
