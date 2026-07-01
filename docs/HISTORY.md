# SQLite History

SQLite history is optional. Constella keeps the realtime dashboard in manager memory, so the service works without a database. Enable SQLite only when persisted GPU rollups and task history are needed.

The database is a side path:

```text
agent sample -> manager memory state -> UI / WebSocket
             -> optional bounded DB queue -> rollups / task sessions
```

Raw 1s GPU metric samples are not written to SQLite in the normal path. The writer keeps only the open 20s rollup buckets in memory, then flushes closed buckets to `gpu_metric_rollups`.

## Enable

Start the manager with `DB_PATH`:

```bash
DB_PATH=run/constella.db RAW_SNAPSHOT_SECONDS=30 ./scripts/service/start.sh
```

`RAW_SNAPSHOT_SECONDS` controls optional low-frequency raw debug snapshots. It defaults to `0`, which disables raw snapshot writes. Raw snapshot retention is controlled by `RAW_RETENTION_SECONDS` during maintenance.

## Retention

- 20s rollups: 7 days
- 2m rollups: 60 days
- 1h rollups: 365 days
- process sessions and process-GPU usage: long-lived
- raw snapshots: optional, default maintenance retention is 12 hours

## Maintenance

Run the bundled maintenance script:

```bash
./scripts/maintenance/db.sh
```

Or run the same command directly:

```bash
uv run constella db maintain --path run/constella.db
```

The maintenance script accepts retention settings:

```bash
DB_PATH=run/constella.db \
RAW_RETENTION_SECONDS=43200 \
SESSION_STALE_SECONDS=300 \
./scripts/maintenance/db.sh
```

Individual commands are also available:

```bash
uv run constella db rollup --path run/constella.db --from-bucket-seconds 20 --to-bucket-seconds 120
uv run constella db rollup --path run/constella.db --from-bucket-seconds 120 --to-bucket-seconds 3600
uv run constella db prune-rollups --path run/constella.db
uv run constella db prune-raw --path run/constella.db
uv run constella db close-sessions --path run/constella.db
```

For an old database that already contains `gpu_metric_samples`, run a one-time migration before pruning or archiving the old raw rows:

```bash
uv run constella db migrate-samples --path run/constella.db --bucket-seconds 20
```

## Runtime Behavior

Database writes use a bounded background queue. Slow or disabled SQLite storage does not block realtime WebSocket snapshots because the dashboard reads the manager's latest in-memory state.

If the DB queue is full, the sink drops that DB write and increments its internal dropped sample counter. Agent ingest, `ClusterState`, `/api/cluster/snapshot`, and `/ws/cluster` continue normally.

When the database is not enabled, history APIs return an empty disabled response:

```json
{"enabled":false,"items":[]}
```

Relevant APIs:

- `GET /api/history/gpu`
- `GET /api/history/tasks`
- `GET /api/users`
