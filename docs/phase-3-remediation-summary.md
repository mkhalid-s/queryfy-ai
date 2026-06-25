# Phase 3 Remediation — What Shipped, What's Deferred

Companion to `docs/architecture-audit-2026-04-16.md`. Captures the
actual landing state of Phase 3 so the next developer can pick up
without re-reading every commit message.

## TL;DR

| Phase  | Status      | Commit range              | Validatable here? |
|--------|-------------|---------------------------|-------------------|
| 3a.1   | ✅ Shipped  | `c96f232`                 | Yes (unit)        |
| 3a.2   | ✅ Shipped  | `874602c`                 | Yes (unit)        |
| 3a.3   | ✅ Shipped  | `58369fd`                 | Yes (unit)        |
| 3b.1   | ✅ Shipped  | `9b2deb5`                 | Yes (unit)        |
| 3b.2   | ✅ Shipped  | `4edcca4`                 | Yes (unit)        |
| 3b.3   | ⚠️ Deferred | —                         | Needs real BigQuery |
| 3b.4   | ⚠️ Deferred | —                         | Needs Snowflake     |
| 3c.1   | ✅ Shipped  | `ad314e6`                 | Yes (unit)        |
| 3c.2   | ✅ Shipped  | `ad314e6`                 | Yes (unit)        |
| 3c.3   | ⚠️ Deferred | —                         | Needs real BigQuery |
| Infra  | ✅ Shipped  | `ca2a78a` / `a67557d` / `bcbc3e8` | Partial (emulators) |

## What shipped (and why it's safe)

### Phase 3a — Data Lake Foundation

- **3a.1 Per-DB timeout map** (`c96f232`): explicit `TOOL_TIMEOUT_BY_DB`
  dict replaces the binary 30s/300s split. BigQuery/Hive/Spark 600s;
  Trino/Presto/Redshift/Snowflake/Databricks 300s; Athena/ClickHouse
  180s; transactional 30s. `AGENT_TOOL_TIMEOUT` is a floor.
- **3a.2 SSE heartbeat** (`874602c`): `_merge_stream_with_heartbeat`
  injects a `heartbeat` event every 15s during quiet periods. Uses
  `asyncio.wait` (not `wait_for`) so the source async generator isn't
  cancelled on timeout. Frontend silently ignores the event.
- **3a.3 Aggregation detection** (`58369fd`):
  `analysis_engines/aggregation_detector.py` (regex-based) attaches
  `aggregated`, `grouping_columns`, `aggregate_columns` to every
  `execute_and_analyze` response. Prerequisite for 3c.1.

### Phase 3b — Async Executors (architecture only)

- **3b.1 Protocol + registry** (`9b2deb5`):
  `app/services/async_executor_protocol.py` — `AsyncExecutorProtocol`
  ABC, `QueryHandle` dataclass, `AsyncExecutorRegistry` singleton.
  `connection_pool_manager.is_async_native_db()` hook. No runtime
  routing change until a concrete driver registers.
- **3b.2 Progress events** (`4edcca4`): `query_progress` SSE event +
  `ToolContext.progress_emitter` callable slot + progress queue
  drained by the heartbeat merger. Frontend recognises the event and
  forwards it via `onEvent`. Drivers emit progress by calling
  `ctx.progress_emitter({"bytes_scanned": …, "percent": …})`.

### Phase 3c — Analytics excellence (subset)

- **3c.1 Aggregated-mode thresholds** (`ad314e6`):
  `detect_insights(data, aggregated=…)` recalibrates detectors for
  GROUP BY results. Trend floor 3 → 5 groups. Anomaly z-score 3.0 →
  2.0 (compensates for thin-tail small-N). Call-site wires the flag
  through from `aggregation_detector.detect_aggregation(sql, cols)`.
- **3c.2 GROUP BY prompt hint** (`ad314e6`): `_aggregation_prompt_hint()`
  appends conditional guidance to `_build_contextual_system_prompt`;
  pushes the LLM toward aggregated SQL for analytical questions.

### Integration test infrastructure

- **Docker Compose stack** (`ca2a78a`): `docker-compose.integration.yml`
  brings up BigQuery emulator (`goccy/bigquery-emulator:0.6.7`) on
  `:9050`, MinIO on `:9000`/`:9001`, Trino `456` on `:8089` with a
  memory connector. Port range avoids dev-stack clashes.
- **Mock long-running query helpers** (`a67557d`):
  `tests/utils/mock_long_running_query.py` — `MockAsyncExecutor`
  (implements the protocol) and `simulate_progress_stream`. Lets
  Phase 3b driver-layer tests run without real credentials.
- **Test data generator** (`bcbc3e8`): `backend/scripts/gen_test_data.py`
  emits paired raw + aggregated JSON fixtures with deterministic seed.

## What's deferred (and what unblocks it)

### 3b.3 — BigQuery async executor

**What's needed**: A real BigQuery project + service-account credentials,
OR use the emulator for basic cases.

**Implementation sketch**:
```python
from google.cloud import bigquery
from app.services.async_executor_protocol import AsyncExecutorProtocol, QueryHandle

class BigQueryAsyncExecutor(AsyncExecutorProtocol):
    def __init__(self, config):
        self._client = bigquery.Client(project=config.project)

    async def start_query(self, sql, **kwargs):
        # bigquery.Client.query() is sync → run in executor thread.
        job = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._client.query(sql)
        )
        return QueryHandle(query_id=job.job_id, db_type="bigquery",
                            driver_state=job)

    async def poll_status(self, handle):
        job = handle.driver_state
        job.reload()  # fetches latest state from BQ
        return {"PENDING": "pending", "RUNNING": "running",
                "DONE": "complete"}.get(job.state, "failed")

    async def fetch_results(self, handle, limit=None):
        job = handle.driver_state
        rows = list(job.result(max_results=limit))
        return {"rows": [dict(r) for r in rows], "columns": [f.name for f in job.schema], "row_count": len(rows)}

    async def cancel(self, handle):
        handle.driver_state.cancel()
        return True

    async def get_progress(self, handle):
        job = handle.driver_state
        return {"bytes_scanned": job.total_bytes_processed} if job.total_bytes_processed else None

# Register at module load:
from app.services.async_executor_protocol import async_executor_registry
async_executor_registry.register("bigquery", BigQueryAsyncExecutor)
```

**Validation checklist before merging**:
1. `docker compose -f docker-compose.integration.yml up -d` — BQ emu reachable
2. `pytest -m data_lake_integration tests/integration/data_lakes/test_bigquery_executor.py`
   (the test file itself needs to be added)
3. Real-cred integration test under `@pytest.mark.requires_real_bigquery`:
   - `start_query` returns handle with non-empty `job_id`
   - `poll_status` transitions PENDING → RUNNING → DONE
   - `cancel` on a running query makes `poll_status` return "cancelled"
   - `get_progress` returns `total_bytes_processed` during a large scan
4. Cost-estimation smoke check (prerequisite for 3c.3).

### 3b.4 — Snowflake async executor

**What's needed**: Snowflake account + user with a warehouse.

**Implementation sketch** (uses `execute_async` + `get_query_status`):
```python
import snowflake.connector
from app.services.async_executor_protocol import AsyncExecutorProtocol, QueryHandle

class SnowflakeAsyncExecutor(AsyncExecutorProtocol):
    def __init__(self, config):
        self._conn = snowflake.connector.connect(**config.connection_kwargs())

    async def start_query(self, sql, **kwargs):
        cur = self._conn.cursor()
        await asyncio.get_running_loop().run_in_executor(None, cur.execute_async, sql)
        return QueryHandle(query_id=cur.sfqid, db_type="snowflake",
                            driver_state=cur)

    async def poll_status(self, handle):
        status = self._conn.get_query_status(handle.query_id)
        return {"QueryStatus.SUCCESS": "complete", ...}[str(status)]
    # ... fetch_results, cancel, get_progress similar
```

**Snowflake-specific notes**:
- `execute_async` returns a cursor whose `.sfqid` is the query_id.
- The SAME connection must be used to poll and fetch results (connection context).
- `get_query_status` values include ABORTED which maps to our "cancelled".
- Progress metadata is poor — just state, no byte count.

### 3c.3 — BigQuery cost estimation

**What's needed**: BigQuery driver (3b.3) + cost-to-dollars config.

**Implementation sketch**:
```python
def estimate_cost(sql, db_config):
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=job_config)
    bytes_processed = job.total_bytes_processed
    cost_usd = bytes_processed / (1024**4) * 5.0  # $5 per TB as of 2024
    return {"bytes": bytes_processed, "estimated_cost_usd": cost_usd}
```

**Not recommended for Athena/Snowflake/Trino** per audit: no unified
cost API, rough row estimates only, ±50% accuracy.

## Feature-flag matrix (rollback cheat sheet)

Every flag defaults True. Flip False for emergency rollback; no
config-only flag requires a deploy.

| Flag                                  | Phase | Behaviour when False                                   |
|---------------------------------------|-------|--------------------------------------------------------|
| `FIX_JSON_ERROR_DETECTION`            | 1 Day 1a | Legacy literal-"Error" string check                 |
| `FIX_SUCCESS_FIELD_CHECK`             | 1 Day 1b | Tool-node masks JSON `success: false` as complete   |
| `FIX_COLUMN_NAME_FIELD`               | 1 Day 2a | Insights lack `column_name` (breaks dedup)          |
| `FIX_INSIGHT_DEDUPLICATION`           | 1 Day 2b | Duplicate insights returned                         |
| `FIX_SMART_ID_EXCLUSION`              | 1 Day 2c | `policy_id` gets trend/concentration analysis       |
| `FIX_DATE_BASED_TRENDS`               | 1 Day 2c | Row index used as time axis (18865% bug)            |
| `FIX_DATA_LAKE_TIMEOUT`               | 1 Day 4  | 30s global timeout on data-lake queries             |
| `FIX_TWO_COUNTER_CIRCUIT_BREAKER`     | 2 Day 1  | Single-counter breaker, threshold 7                 |
| `FIX_DISTRIBUTED_LOCK_FAIL_LOUD`      | 2 Day 3  | Silent local-lock fallback in prod                  |
| `FIX_BACKGROUND_LOCK_EXTENSION`       | 2 Day 3  | Event-driven inline extension (missed quiet periods)|
| `FIX_POOL_PREFLIGHT`                  | 2 Day 3  | No SELECT 1 before yielding pooled conn             |
| `FIX_DB_SPECIFIC_TIMEOUTS`            | 3a.1     | Binary 30s/300s split (Phase 1 Day 4 behaviour)     |
| `FIX_SSE_HEARTBEAT`                   | 3a.2     | No heartbeats; quiet SSE streams dropped by proxies |
| `FIX_AGGREGATION_DETECTION`           | 3a.3     | No `aggregated` flag; 3c.1 can't recalibrate        |
| `FIX_QUERY_PROGRESS_EVENTS`           | 3b.2     | No progress queue; drivers can't surface metrics    |
| `FIX_AGGREGATED_MODE_THRESHOLDS`      | 3c.1     | Detectors use raw thresholds on aggregated data     |
| `FIX_PROMPT_AGGREGATION_HINT`         | 3c.2     | LLM gets no GROUP BY nudge; may emit SELECT *       |
| `DEVELOPMENT_MODE`                    | 2 Day 3  | Permits process-local lock fallback (NOT for prod)  |

## Running the emulator smoke suite

```bash
# Start stack
docker compose -f docker-compose.integration.yml up -d

# Wait for healthchecks (~30s)
docker compose -f docker-compose.integration.yml ps

# Run emulator-dependent tests
cd backend && pytest -m data_lake_integration

# Expected: BQ emulator discovery + Trino /v1/info + MinIO reachability
# all PASS when stack is up; all SKIP when down.

# Tear down
docker compose -f docker-compose.integration.yml down -v
```

See `docs/integration-testing.md` for the full marker matrix and
environment-variable overrides.

## Driver-implementation checklist for 3b.3 / 3b.4

When picking up the deferred driver work:

1. Create the file: `app/services/executors/bigquery_async.py` (or
   `snowflake_async.py`).
2. Implement every abstract method on `AsyncExecutorProtocol`. Missing
   one → `TypeError` at instantiation (tested in 3b.1).
3. Register at module load via `async_executor_registry.register(...)`.
4. Add a corresponding integration test in
   `tests/integration/data_lakes/` guarded by the right marker
   (`requires_real_bigquery` or `requires_real_snowflake`). Skipped
   cleanly in CI without creds.
5. Update the pool manager's `get_connection` branch so
   `is_async_native_db(db_type) == True` routes to the registered
   executor instead of `_get_sync_connection`.
6. Wire `ctx.progress_emitter` into the driver's poll loop (every
   ~1s during running).
7. Verify the cancellation path: simulate a timeout and assert the
   query is actually cancelled server-side, not just the Python task.

All scaffolding to satisfy these checkpoints is already in main via
Phase 3b.1 / 3b.2. No further abstraction work needed.
