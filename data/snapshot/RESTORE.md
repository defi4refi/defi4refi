# defi4refi database snapshot

Point-in-time export of the ClickHouse `defi4refi` database. Lets the lead
pipeline be rebuilt offline — ClickHouse does not need to stay running.

## Contents

- `*.jsonl.gz` — one JSON object per row (`JSONEachRow` format), gzipped.
  **Privacy-scrubbed for the public repo**: the `contacts` table is excluded
  and email addresses embedded in other tables are replaced with
  `[redacted-email]`. Unscrubbed copies live locally in
  `data/snapshot-private/` (gitignored).
- `ddl/*.sql` — `SHOW CREATE TABLE` output for each table
- `../../scripts/score.sql`, `../../scripts/outreach_queue.sql` — view definitions (recreated on top of restored tables)

## Restore

```bash
# 1. start ClickHouse (docker compose up -d clickhouse)
# 2. create database + tables
curl -s http://localhost:8123/ --data "CREATE DATABASE IF NOT EXISTS defi4refi"
for f in ddl/*.sql; do
  curl -s http://localhost:8123/ --data-binary @"$f"
done
# 3. load rows
for f in *.jsonl.gz; do
  t="${f%.jsonl.gz}"
  zcat "$f" | curl -s http://localhost:8123/ \
    --data-binary @- \
    --get --data-urlencode "query=INSERT INTO defi4refi.$t FORMAT JSONEachRow"
done
# 4. recreate views (see scripts/score.sql and scripts/outreach_queue.sql)
```

## Query without ClickHouse

The `.jsonl.gz` files are plain JSONL — usable with `duckdb`, `pandas`,
`jq`, or any JSON tooling:

```bash
duckdb -c "SELECT * FROM read_json('raw_leads.jsonl.gz') LIMIT 5"
```

Snapshot taken: 2026-09-17. Regenerate by re-running the
`SELECT * ... FORMAT JSONEachRow | gzip` export loop from git history.
