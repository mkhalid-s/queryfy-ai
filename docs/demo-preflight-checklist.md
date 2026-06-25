# Demo Pre-flight Checklist

Run before every live demo. Catches the failure modes identified in
`docs/architecture-audit-2026-04-16.md` that historically broke demos but
are not covered by unit tests (configuration, connectivity, stale cache).

## 1. Automated preflight

From the repo root:

```bash
./scripts/demo-preflight.sh --clear-cache --backend-url http://localhost:8000
```

Expected: exit 0, zero ERRORs in the validator output, `/health/live` green,
caches cleared. If any ERROR appears, fix it before moving on — every ERROR
is a known cause of a demo-time failure.

## 2. Fix-flag sanity check

```bash
curl -s http://localhost:8000/health/diagnostic | jq '.fix_flags'
```

All reliability fix flags should be `true`. **Phase 1 (demo-critical):**

- `json_error_detection`
- `success_field_check`
- `column_name_field`
- `insight_deduplication`
- `smart_id_exclusion`
- `date_based_trends`
- `data_lake_timeout`

**Phase 2 (production resilience):**

- `two_counter_circuit_breaker`
- `distributed_lock_fail_loud`
- `background_lock_extension`
- `pool_preflight`

**Phase 3a (data-lake foundation):**

- `db_specific_timeouts`
- `sse_heartbeat`
- `aggregation_detection`

**Phase 3b (async-executor plumbing):**

- `query_progress_events`

**Phase 3c (analytics excellence):**

- `aggregated_mode_thresholds`
- `prompt_aggregation_hint`

**Phase 4 (size-unbounded analysis):**

- `result_cache` — full rows cached server-side under `rows_ref`. Off
  reverts to the legacy 1000-row sampling path that historically
  triggered the "Result too large for processing" agent retry loop on
  queries returning >5K rows. Strongly recommended **`true`** for any
  demo that involves >1K-row results.

A `false` on any of the above is a signalled rollback — intentional if
you are debugging, a mistake if it predates the demo.

`development_mode` is surfaced separately — it should be **`false`** in
any prod-like demo environment (Redis must be reachable). `true` is only
safe for an air-gapped local dev demo where the single worker doesn't
need cross-process lock serialisation.

## 3. Manual scenario matrix

Run each scenario in analyst mode (or standard mode where noted). Mark
pass/fail. Every scenario should complete without a browser console error
and without the "no results found" false negative.

| # | Scenario | DB / data | Expected outcome |
|---|----------|-----------|------------------|
| 1 | Empty table | any SQL DB, empty table | Clear "0 rows" message, not "query failed" |
| 2 | 10-row aggregate | any SQL DB, `SELECT region, SUM(revenue) GROUP BY region` | Chart rendered; insights with `column_name` present |
| 3 | 1,000-row detail query | any SQL DB | Table renders; analysis completes; one trend per metric (no duplicates) |
| 4 | 10,000-row dataset | any SQL DB | Sampling disclaimer shown; memory guard not triggered |
| 5 | Table with all-unique `policy_id` | any SQL DB | `policy_id` does NOT appear in numeric insights (smart ID exclusion) |
| 6 | Table with `region_id` (20 distinct values) | any SQL DB | `region_id` DOES appear in concentration/comparison insights |
| 7 | Date-series query | any SQL DB, grouped by month | Trend slope reported in "per day", recommendation mentions total days |
| 8 | Schema-qualified name | e.g. `demoapp.policies` | Query executes; no "suspicious patterns" false rejection |
| 9 | SQL with `--` comment | LLM-generated SQL | Query passes validation (Day 3 fix) |
| 10 | Data-lake query taking >30s | BigQuery / Snowflake | Does NOT time out at 30s; completes or extends to the per-DB 300s ceiling |
| 11 | Network blip mid-stream | simulate by toggling wifi briefly | SSE auto-reconnects (synthetic `reconnecting` event) |
| 12 | Malformed chart spec | backend returns broken annotations | Chart renders without annotations OR empty-state message; no blank canvas |
| 13 | Concurrent submissions | fire two chats from same session fast | Second receives a clear "already running" response, not a silent stall |
| 14 | MongoDB in analyst mode | (known limitation) | Documented failure mode — use standard mode for MongoDB |

## 4. Demo-start procedure

1. `./scripts/demo-preflight.sh --clear-cache` — must exit 0.
2. Verify the vector DB has at least one indexed schema (otherwise the
   agent has no schema context and every query fails):
   ```bash
   curl -s http://localhost:8000/api/v1/data-dictionary/search?query=table | jq '.results | length'
   ```
   Expect a non-zero count. If zero, run the schema-reindex flow first.
3. Launch the frontend, open browser devtools, confirm no console errors
   on load.
4. Run scenario #2 (10-row aggregate) as a warm-up — if this fails, the
   broader demo will too.

## 5. Post-demo debrief

After the demo, capture the final diagnostic snapshot to confirm which
fixes were exercised:

```bash
curl -s http://localhost:8000/health/diagnostic | jq '.fix_events'
```

Any counter `> 0` means that fix caught a bug during the demo (good — it's
working). `json_error_detection` and `success_field_check` are the highest-
value indicators that Day 1 fixes are active in production.
