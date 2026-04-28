# Migration plan — Partition `price_snapshots` by day

Status: **deferred**. Empty pre-deploy; this plan executes when
operational signal warrants it (see Trigger).

## Trigger

`price_snapshots` row count > ~1 million. Check with:

```sql
SELECT count(*) FROM price_snapshots;
SELECT pg_size_pretty(pg_total_relation_size('price_snapshots'));
```

The model docstring (`src/pumpwatch/db/models/price_snapshot.py`)
mentions ~10 M as a hard threshold, but partitioning gets *easier* the
emptier the table is. Aim to migrate around 1 M to keep the cutover
window small.

## Strategy

Declarative `RANGE(ts)` partitioning, one child table per UTC day.
Parent table holds the schema; reads/writes go through it transparently.

- **Parent**: `price_snapshots` (partitioned by `ts`).
- **Children**: `price_snapshots_YYYYMMDD` covering `[YYYYMMDD 00:00 UTC,
  YYYY(MM+1)DD 00:00 UTC)`. Pre-create the next 7 days at migration
  time.
- **New Beat task** `pumpwatch.scheduler.create_tomorrows_partition`
  scheduled at `0 23 * * *` UTC; idempotent
  `CREATE TABLE IF NOT EXISTS`.
- **Local index** on `(token_address, ts)` per partition (Postgres 16
  propagates the parent's index to new partitions automatically when
  declared on the parent before any partition exists).

## Migration shape

Single Alembic revision. The table is near-empty at trigger time, so a
rename + recreate + copy + drop pattern works without a long-held
exclusive lock.

```python
# alembic/versions/<rev>_partition_price_snapshots.py

def upgrade() -> None:
    op.execute("ALTER TABLE price_snapshots RENAME TO price_snapshots_old")

    # Drop FK from alerts_sent so we can recreate it against the new parent.
    op.drop_constraint("fk_alerts_sent_price_snapshot_id", "alerts_sent", type_="foreignkey")

    op.execute("""
        CREATE TABLE price_snapshots (
            id BIGSERIAL,
            token_address TEXT NOT NULL REFERENCES tokens(address) ON DELETE CASCADE,
            market_cap_usd NUMERIC(20, 4),
            price_usd NUMERIC(28, 12),
            volume_5m_usd NUMERIC(20, 4),
            liquidity_usd NUMERIC(20, 4),
            holder_count INTEGER,
            source TEXT NOT NULL DEFAULT 'pumpfun',
            ts TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, ts)
        ) PARTITION BY RANGE (ts);
    """)
    op.execute(
        "CREATE INDEX ix_price_snapshots_token_ts ON price_snapshots "
        "USING btree (token_address, ts);"
    )

    # Pre-create today + next 7 days.
    for offset in range(8):
        op.execute(
            f"CREATE TABLE price_snapshots_{_day(offset)} PARTITION OF price_snapshots "
            f"FOR VALUES FROM ('{_iso(offset)}') TO ('{_iso(offset + 1)}');"
        )

    op.execute("INSERT INTO price_snapshots SELECT * FROM price_snapshots_old")
    op.execute("DROP TABLE price_snapshots_old")

    op.create_foreign_key(
        "fk_alerts_sent_price_snapshot_id",
        "alerts_sent",
        "price_snapshots",
        ["price_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Reverse the rename pattern: dump partitioned rows into a flat copy.
    op.drop_constraint("fk_alerts_sent_price_snapshot_id", "alerts_sent", type_="foreignkey")
    op.execute("ALTER TABLE price_snapshots RENAME TO price_snapshots_partitioned")
    op.execute("""
        CREATE TABLE price_snapshots (
            id BIGSERIAL PRIMARY KEY,
            token_address TEXT NOT NULL REFERENCES tokens(address) ON DELETE CASCADE,
            market_cap_usd NUMERIC(20, 4),
            price_usd NUMERIC(28, 12),
            volume_5m_usd NUMERIC(20, 4),
            liquidity_usd NUMERIC(20, 4),
            holder_count INTEGER,
            source TEXT NOT NULL DEFAULT 'pumpfun',
            ts TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute(
        "CREATE INDEX ix_price_snapshots_token_ts ON price_snapshots "
        "USING btree (token_address, ts);"
    )
    op.execute("INSERT INTO price_snapshots SELECT * FROM price_snapshots_partitioned")
    op.execute("DROP TABLE price_snapshots_partitioned CASCADE")
    op.create_foreign_key(
        "fk_alerts_sent_price_snapshot_id",
        "alerts_sent",
        "price_snapshots",
        ["price_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
```

Helpers `_day(offset)` and `_iso(offset)` produce `YYYYMMDD` and
`YYYY-MM-DD` strings relative to today (UTC).

## New Beat task

```python
# src/pumpwatch/scheduler/tasks.py

@celery_app.task
def create_tomorrows_partition() -> None:
    target = (datetime.now(UTC) + timedelta(days=1)).date()
    nxt = target + timedelta(days=1)
    name = f"price_snapshots_{target.strftime('%Y%m%d')}"
    # Idempotent: the IF NOT EXISTS guards re-runs.
    sql = (
        f"CREATE TABLE IF NOT EXISTS {name} "
        f"PARTITION OF price_snapshots "
        f"FOR VALUES FROM ('{target.isoformat()}') TO ('{nxt.isoformat()}');"
    )
    # ... execute against the sessionmaker ...
```

Add a Beat entry in `src/pumpwatch/celery_app.py`:

```python
"create-tomorrows-partition": {
    "task": "pumpwatch.scheduler.tasks.create_tomorrows_partition",
    "schedule": crontab(hour=23, minute=0),
},
```

## Retention

Optional, when storage matters: detach + drop partitions older than N
days.

```python
@celery_app.task
def detach_old_partitions(retain_days: int = 90) -> None:
    cutoff = (datetime.now(UTC) - timedelta(days=retain_days)).date()
    # Query pg_partitions, DETACH any with upper bound <= cutoff, optionally DROP.
```

Don't enable retention until the team has decided whether the dropped
data is reconstructible (it isn't, by default — DLQ entries and
`alerts_sent` rows reference snapshot IDs).

## Verification

1. **Round-trip the migration on a populated dev DB.**

   ```bash
   docker compose exec postgres pg_dump -U pumpwatch -d pumpwatch \
     -t price_snapshots --data-only > /tmp/snapshots.before.sql

   docker compose run --rm bot alembic upgrade head
   docker compose exec postgres pg_dump -U pumpwatch -d pumpwatch \
     -t price_snapshots --data-only > /tmp/snapshots.after.sql

   diff /tmp/snapshots.before.sql /tmp/snapshots.after.sql  # should be empty

   docker compose run --rm bot alembic downgrade -1
   docker compose run --rm bot alembic upgrade head
   ```

2. **Unit-test the Beat task** against a real Postgres:

   ```python
   async def test_create_tomorrows_partition_is_idempotent(...):
       # Run twice; expect no error, expect partition to exist.
   ```

3. **Smoke test the worker write path** post-migration. The worker
   should not need any code change — the partitioned parent looks the
   same to the ORM.

## Why this isn't shipping in Session 8

- `price_snapshots` is empty at cutover; partitioning empty tables
  has no real benefit.
- The migration adds operational surface (one more daily Beat task,
  a cron-triggered child create) for a problem we don't have yet.
- The current `(token_address, ts)` index is partition-friendly when
  we do migrate; nothing in the schema needs to change preemptively.

When this plan executes, link the resulting Alembic revision and Beat
task PR back here and update the status line above to **executed**.
