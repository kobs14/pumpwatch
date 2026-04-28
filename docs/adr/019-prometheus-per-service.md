# ADR 019 — Per-service Prometheus `/metrics` endpoints

## Context

PumpWatch is four separately-running services (bot, scheduler, worker,
alerts) plus Postgres and Redis. Each service has metrics worth
exporting — alert counts, source-call statuses, queue depth, DLQ
size, suppression reasons. The Prometheus scraping model needs a
stable HTTP endpoint per scrape target.

A monolithic `/metrics` endpoint on a single sidecar would mean every
service writes to the same metrics process, which we don't have a
clean shape for. A per-service endpoint is simpler — each service
binds its own `prometheus_client.start_http_server(port)` call.

The wrinkle is the worker. Celery uses a prefork pool with
`--concurrency=4`; counters incremented in forked children are
*invisible* to the master process unless `prometheus_client` runs in
multi-process mode, which is selected by setting
`PROMETHEUS_MULTIPROC_DIR` *before* any metric is constructed.

## Decision

- Each service binds its own `/metrics` port (defaults: bot 9101,
  scheduler 9102, worker 9103, alerts 9104). Exposed via
  `pumpwatch.observability.metrics.start_metrics_server(port)`, which
  is idempotent and detects multi-proc mode at bind time.
- The worker container sets `PROMETHEUS_MULTIPROC_DIR=/tmp/pumpwatch-metrics`
  in `docker-compose.yml`'s `worker.environment`, so the env var is
  in place *before Python imports anything*. Setting it in a Celery
  `worker_init` signal handler is too late (lessons.md Session 7).
- Prometheus and Grafana ship behind `--profile observability` in
  Compose. Default `docker compose up` does not start them; this ADR
  is about the metric exposure surface, not the scrape stack.
- The dashboard at `ops/grafana/dashboards/pumpwatch.json` is
  auto-provisioned and covers the six metrics:
  `pumpwatch_alerts_fired_total{type}`,
  `pumpwatch_alerts_suppressed_total{reason}`,
  `pumpwatch_alerts_delivery_failed_total`,
  `pumpwatch_source_calls_total{source,status}`,
  `pumpwatch_celery_queue_depth{queue}`,
  `pumpwatch_dlq_size`.

## Consequences

- Adding a metric is a one-line change in `observability/metrics.py`
  plus the increment site. No coordination across services.
- Production exposure: `/metrics` ports must NOT be public. The
  deployment guide (`docs/deployment.md`) covers this — bind to
  the internal Docker network, scrape from in-cluster Prometheus,
  reach Grafana via SSH tunnel or Caddy basic-auth.
- Prefork multiprocessing has a quirk: gauges have to declare a
  multiprocess mode (`livesum`/`liveall`/`min`/`max`) explicitly. Our
  gauges (`celery_queue_depth`, `dlq_size`) refresh on a periodic
  Beat task (`refresh_gauges`) so the `liveall` default is correct.

## Status

Accepted, 2026-04 (Session 7).
