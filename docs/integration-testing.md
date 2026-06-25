# Integration Testing — Data Lake Drivers

Test infrastructure for Phase 3b (BigQuery / Snowflake / Trino async
executors) and Phase 3c (aggregated-mode insights, cost estimation).
Lets driver code run against local emulators without real cloud
credentials.

## TL;DR

```bash
# Start emulators
docker compose -f docker-compose.integration.yml up -d

# Run the integration suite
cd backend && pytest -m data_lake_integration

# Tear down (removes MinIO volumes)
docker compose -f docker-compose.integration.yml down -v
```

## What runs where

| Target                  | Local emulator                          | Real credentials needed    | Pytest marker                       |
|-------------------------|-----------------------------------------|----------------------------|-------------------------------------|
| BigQuery                | `goccy/bigquery-emulator` on `:9050`    | No (basic) / Yes (full)    | `requires_bigquery_emulator` / `requires_real_bigquery` |
| Trino / Athena          | `trinodb/trino` on `:8089`              | No                         | `requires_trino`                    |
| MinIO (S3)              | `minio/minio` on `:9000`                | No                         | `requires_minio`                    |
| Snowflake               | None (cloud only)                       | Yes                        | `requires_real_snowflake`           |
| Databricks / Redshift   | None (cloud only)                       | Yes (per-provider setup)   | —                                   |

## Pytest markers (see `backend/pytest.ini`)

| Marker                        | Meaning                                                           |
|-------------------------------|-------------------------------------------------------------------|
| `data_lake_integration`       | Auto-applied to everything under `tests/integration/data_lakes/`  |
| `requires_bigquery_emulator`  | Skipped unless `BIGQUERY_EMULATOR_URL` responds                   |
| `requires_trino`              | Skipped unless `TRINO_URL` responds                               |
| `requires_real_bigquery`      | Skipped unless `GOOGLE_APPLICATION_CREDENTIALS` + `BIGQUERY_PROJECT` set |
| `requires_real_snowflake`     | Skipped unless `SNOWFLAKE_ACCOUNT` / `_USER` / `_PASSWORD` set    |

Fixtures in `tests/integration/data_lakes/conftest.py` probe each
service with a fast TCP connect and `pytest.skip()` the test when
unreachable — safe to run in CI without the stack up; tests vanish.

## Environment overrides

| Variable                              | Default                     |
|---------------------------------------|-----------------------------|
| `BIGQUERY_EMULATOR_URL`               | `http://localhost:9050`     |
| `TRINO_URL`                           | `http://localhost:8089`     |
| `MINIO_URL`                           | `http://localhost:9000`     |
| `GOOGLE_APPLICATION_CREDENTIALS`      | (unset — disables real BQ)  |
| `BIGQUERY_PROJECT`                    | (unset)                     |
| `SNOWFLAKE_ACCOUNT` / `_USER` / `_PASSWORD` | (unset)               |

## Limitations of the emulators

**BigQuery emulator (`goccy/bigquery-emulator`)** is a SQLite-backed
reimplementation of the BigQuery REST API. Good enough for:
- QueryJob lifecycle (insert → running → done)
- `dry_run` byte-count estimation
- Streaming inserts against test datasets
- Async polling semantics

It does **not** implement:
- Partitioned tables, clustering, materialized views
- User-defined functions (JavaScript UDFs in particular)
- IAM / authorisation checks (every request is "authorised")
- Billing / quotas
- Some warehouse-specific SQL (ARRAY_AGG edge cases, approximate aggregates)

Tests that exercise those features must be gated
`@pytest.mark.requires_real_bigquery` and only run with credentials.

**Trino (`trinodb/trino`)** is the real engine, configured with the
memory connector (no persistent state). Catalogs are reset on every
`docker compose down -v`. Use it as a drop-in for Athena / Presto
async semantics testing.

**Snowflake has no emulator.** Snowflake is cloud-only. Driver code
for Snowflake (Phase 3b.4) is validated exclusively against a real
account via `requires_real_snowflake`. Consider DuckDB as a local
stand-in for SQL-parity testing (see `docker-compose.analytics.yml`).

## Ports

`docker-compose.integration.yml` uses a port range distinct from
`docker-compose.dev.yml` to avoid clashes:

| Port   | Service             |
|--------|---------------------|
| `9050` | BigQuery emulator   |
| `9000` | MinIO S3 API        |
| `9001` | MinIO web console   |
| `8089` | Trino coordinator   |

## When to run

- **On every PR touching Phase 3b driver code** (3b.3 BigQuery, 3b.4 Snowflake).
- **Before cutting a release** as a smoke check that emulators still
  match the protocols we expect.
- **Not on every local `pytest` run** — unit tests cover the
  driver-agnostic layers (protocol, registry, progress plumbing).

## What's NOT here

- Real BigQuery query billing simulation (emulator doesn't track cost).
- Real Snowflake warehouse scaling behaviour (requires account).
- Full Iceberg / Delta catalog backed by MinIO (can be added if Phase 3
  scope widens).

Add real-cred integration tests under `tests/integration/data_lakes/`
and mark them with `requires_real_bigquery` / `requires_real_snowflake`.
They'll skip cleanly in environments without credentials.
