# Architecture Audit: nl2sql-app Analyst Mode
**Date:** 2026-04-16
**Scope:** Full-stack audit of ReAct agent, analytics pipeline, infrastructure, and frontend
**Method:** 7 deep-dive audits across backend and frontend, plus manual investigation

---

## Executive Summary

The analyst mode has **5 systemic architectural problems** that produce cascading failures. These are not isolated bugs -- they are structural issues where the system's design guarantees fragility. Patching individual symptoms will not make this demo-ready.

**By the numbers:**
- 11 CRITICAL issues (break functionality outright)
- 18 HIGH issues (unreliable under real conditions)
- ~25 MEDIUM issues (degrade quality)
- 7 layers of data transformation with no shared contract
- 6 different size limits that conflict with each other
- 10+ locations where errors are disguised as "no results"

---

## The 5 Systemic Problems

### Problem 1: The Serialization Chain of Death

Data passes through 7 transformation hops from database to browser. Each layer independently serializes, truncates, and reinterprets data with no shared schema.

```
DB Row (native types)
  -> Executor: datetime->isoformat, Decimal->float           [Layer 1]
  -> DatabaseService: hasattr(isoformat)/hasattr(__float__)   [Layer 2]
  -> execute_and_analyze: sanitize_value (100-char truncate)  [Layer 3]
  -> json.dumps(ensure_ascii=False, default=str)              [Layer 4]
  -> ToolRegistry: TEXT_LIMIT=10KB truncation (BREAKS JSON)   [Layer 5]
  -> react_agent tool_node: json.loads (FAILS on broken JSON) [Layer 6]
  -> SSE streaming: json.dumps again for event envelope       [Layer 7]
```

**Size limits that conflict:**

| Layer | Limit | What Happens When Exceeded |
|-------|-------|---------------------------|
| Memory guard | 50 MB | Returns error (correct) |
| Analysis sampling | 1,000 rows | Samples randomly (loses time-series order) |
| ToolRegistry JSON | 50 KB | Returns error (correct) |
| ToolRegistry text | 10 KB | **Slices string mid-JSON (BREAKS PARSING)** |
| sanitize_value | 100 chars | Silent truncation per string field |
| prepare_for_analysis | 500 chars | Silent truncation for analysis |
| DB query limit | Configurable | Agent adds LIMIT clause |

**The critical break:** Tools return JSON *strings* (not dicts). The ToolRegistry classifies them as "plain text" and applies the 10KB text limit, slicing the JSON at an arbitrary byte boundary. The consumer then fails to parse the corrupted JSON and reports "no results" to the user.

**What must change:** Single serialization point. Tools return dicts. One layer serializes. No re-parsing.

---

### Problem 2: Errors Disguised as Empty Results

10+ locations in the codebase catch exceptions and return `{"success": True, "row_count": 0}`. The user sees "query returned no results" when the actual problem is a connection failure, JSON parse error, timeout, or truncation.

**Locations where errors become "no results":**

| File | Line | Trigger | User Sees |
|------|------|---------|-----------|
| query_tools.py | 169 | `not result` (executor returns None) | "No results" |
| query_tools.py | 644 | `not result.get('rows')` | "No results" |
| react_agent.py | 1624-1632 | JSON parse failure on tool result | "0 rows returned" |
| react_agent.py | 1542-1545 | execute_sql JSON parse failure | "No results" |
| react_agent.py | 787-788 | row_count == 0 (from any cause) | "Data does not exist" |

**The compounding effect:** When errors are masked as success:
- `consecutive_failures` counter is RESET to 0 (react_agent.py:1645)
- `status` is forced to "complete" (react_agent.py:1644)
- The circuit breaker never triggers
- Error tracking is completely bypassed

**What must change:** Distinguish between "query returned zero rows" (legitimate) and "processing failed" (error). Never set `success: True` in an exception handler.

---

### Problem 3: Analysis Engines Have No Column Intelligence

The insight detector treats every numeric column identically -- `policy_id`, `revenue`, `count`, `zip_code` all get trend analysis, concentration analysis, and anomaly detection. ID columns produce nonsensical insights.

**Root causes:**

1. **No ID column exclusion** (insight_detector.py:76-79): `_get_numeric_columns()` returns every column where the first row's value is numeric, including `policy_id`, `customer_id`, etc.

2. **Row index used as time axis** (insight_detector.py:165-235): Trend detection uses `enumerate()` index as x-coordinate instead of actual date values. Result: "policy_id shows increasing trend of 18865%" (computing regression on row_number vs ID value).

3. **No deduplication** (insight_detector.py:40-61): Four detectors (concentration, trend, anomaly, comparison) can all generate insights about the same column. No dedup means duplicate/near-duplicate insights.

4. **5 copies of column detection logic** spread across insight_detector.py, statistics.py, chart_intelligence.py, data_quality.py, and comparisons.py -- each with different behavior.

**What must change:** Unified `ColumnClassifier` that runs once, classifies columns (ID/numeric/categorical/date/text), and is shared by all engines.

---

### Problem 4: LangGraph State Machine Has No Safety Guarantees

The ReAct agent's state machine has fundamental design flaws that cause silent failures, infinite loops, and data loss.

**Critical state machine issues:**

1. **Incomplete state returns** (react_agent.py:1454): When `tool_node` is called but the last message has no tool_calls, it returns `{"messages": []}` -- only updating messages, leaving ALL other state fields (status, counters, execution_result) stale from the previous iteration.

2. **Checkpoint resume mutates state in-place** (react_agent.py:2635): `state.values["messages"].append(HumanMessage(...))` directly mutates the checkpoint object. If two concurrent requests resume the same checkpoint, both append their question to the same list.

3. **Message truncation breaks tool call pairing** (react_agent.py:1315): The MessageTruncator removes old messages to fit context, but can orphan tool calls (AIMessage with tool_calls kept, corresponding ToolMessages removed) or orphan tool results (ToolMessages kept, AIMessage removed). LangChain requires these to be paired.

4. **Circuit breaker both too aggressive AND bypassable:**
   - Too aggressive: `iterations_without_execution` increments on every non-SQL tool call. 7 schema lookups (legitimate for complex JOINs) triggers the breaker.
   - Bypassable: Parse failures set `consecutive_failures: 0`, preventing the breaker from ever triggering on repeated parse errors.

5. **Tool timeout doesn't cancel execution** (react_agent.py:1493): `asyncio.wait_for` raises TimeoutError but the tool coroutine continues executing in the background. Retry creates a second concurrent execution.

**What must change:** State machine needs formal state contracts (each node declares what it reads/writes), deep-copy on checkpoint resume, and proper coroutine cancellation.

---

### Problem 5: Infrastructure Assumes Happy Path

The infrastructure layer silently degrades when any dependency is unavailable, making failures invisible to health checks and operators.

**Critical infrastructure gaps:**

1. **Distributed lock silently falls back to local** (distributed_lock.py:206-254): When Redis is unavailable, the lock falls back to a process-local asyncio.Lock. In multi-worker deployment, two workers can run the agent concurrently for the same session, corrupting checkpoint state.

2. **Health checks don't test actual connectivity** (health.py:136-195): The `/health/live` endpoint returns hardcoded "healthy". The `/health/ready` endpoint checks Redis but NOT the user's database. Load balancer routes traffic to instances that can't reach the database.

3. **Connection pool cleanup races with queries** (connection_pool_manager.py:797-823): The cleanup loop closes idle pools without checking if a connection from that pool is currently in use by a query. Causes transient "connection closed" errors.

4. **No graceful shutdown** (main.py:284-324): On shutdown, connection pools are closed immediately without draining in-flight requests. Active queries get "connection closed" errors.

5. **No connection health check before use** (connection_pool_manager.py:620-622): Cached pools are returned without validation. A pool with dead connections is handed to callers, causing mid-query failures.

**What must change:** Health checks must test real connectivity. Lock fallback must fail loudly. Connection pools need pre-flight validation.

---

## Frontend Issues

The frontend compounds backend problems by masking errors and lacking resilience:

| Issue | Severity | Impact |
|-------|----------|--------|
| No SSE auto-reconnect | HIGH | Network blip kills the entire analysis; user must retry manually |
| Malformed JSON events silently dropped | HIGH | Partial results shown as complete |
| No chart config validation | HIGH | Malformed chart config -> blank space, no error message |
| No virtual scrolling for tables | HIGH | 50+ rows with 20 columns = 1000 DOM nodes, causes lag |
| Generic error messages | HIGH | "Stream disconnected" -- user can't tell if network or server |
| No request queueing when offline | HIGH | Message lost if sent during brief network drop |
| Conversation store unbounded | MEDIUM | localStorage can exceed 5MB quota with large result sets |
| No loading state flag | MEDIUM | UI infers loading from message type -- race conditions |

---

## End-to-End Data Flow (Current State)

```
User HTTP Request (POST /api/chat)
    |
chat.py: Validate, create session, acquire distributed lock
    |
ReActAgentNodes: Initialize LangGraph state
    |
run_streaming() async generator
    |
graph.astream() -> agent_node
    | (message truncation: 4000 tokens - CAN BREAK TOOL PAIRING)
LLM call via ToolCallingService
    | (tool specs from ToolRegistry)
Tool selection + argument generation
    |
LangGraph routing: should_continue
    |
tool_node execution
    | (LIMIT clause stripping for execute_and_analyze)
ToolRegistry.execute
    | (RETURNS STRING - treated as plain text)
    | (TEXT_LIMIT=10KB TRUNCATION - CAN BREAK JSON)
execute_and_analyze handler
    | (memory guard: 50MB, sampling: >1000 rows)
DatabaseService.execute_query
    | (cache lookup, read-only validation)
Database executor (type-specific)
    | (isoformat() for dates, float() for decimals)
Results -> prepare_for_analysis (string truncation: 500 chars)
    |
Analysis engines (5 separate column detection implementations)
  - compute_statistics (full data if <=10000 rows)
  - detect_insights (NO ID EXCLUSION, ROW INDEX AS TIME AXIS)
  - assess_data_quality
  - recommend_chart
  - enhance_insights_with_llm (control chars from LLM not sanitized)
    | (sanitize_dict: NaN/Infinity only, NOT control chars)
Output serialization
    | (ensure_ascii=False, allow_nan=False, default=str)
    | (RETURNS JSON STRING to ToolRegistry)
tool_node result parsing
    | (json.loads - FAILS if ToolRegistry truncated the string)
    | (fallback: success=True, row_count=0 - MASKS THE ERROR)
State update: execution_result
    |
answer_node: bypass AnswerGenerator if has_analysis=True
    |
run_streaming: state accumulation + event emission
    |
SSE formatting: json.dumps each event -> "data: {...}\n\n"
    |
Browser: fetch() ReadableStream
    | (NO auto-reconnect, NO partial event buffering)
Vue components: render results, insights, charts
    | (NO chart validation, NO virtual scrolling)
User sees result (or "no results" if anything above broke)
```

---

## Remediation Plan (Battle-Tested)

*This plan was stress-tested by 4 independent review agents that found gaps in the
original proposal. Every fix below has been validated for feasibility, side effects,
and interaction with standard mode.*

### Key Corrections from Reviews (3 rounds, 16 agents total)

**Round 2 — Feasibility Review (4 agents):**

1. **"Tools return dicts" is WRONG.** LangChain's ToolMessage.content MUST be a string.
   ToolRegistry already returns strings. The real fix: make the ToolRegistry JSON-aware
   for string results (already partially done 2026-04-16). Keep the string contract.

2. **Error detection at line 1503 is SECONDARY.** The REAL bug is at lines 1594-1602:
   when execute_and_analyze JSON parses successfully with `success: false`, the code
   STILL returns `status: "complete"` and resets all failure counters. Must add a success
   check INSIDE the execute_and_analyze success path, not just at the error detection gate.

3. **ID column heuristic is too aggressive.** `region_id` is analytically valuable for
   concentration ("80% of claims from 3 regions"). Need cardinality-aware exclusion,
   not name-only heuristic.

4. **Aggregation pushdown is NOT Phase 1.** Review found: 4-8 weeks effort, analysis
   engines produce DIFFERENT insights on aggregated data, no SQL transformation layer
   exists for multi-DB support. Current sampling approach already handles most scenarios.

5. **Standard mode is safe.** It uses a completely separate code path
   (SQLGenerationService), no tools/ToolRegistry/ReAct. Tool-level changes won't break it.

6. **AGENT_TOOL_TIMEOUT = 30s kills ALL data lake queries.** Every BigQuery/Snowflake/Athena
   query that takes >30s fails instantly while still running in the background, consuming cost.

**Round 3 — Final Code Validation (3 agents):**

7. **Insight dedup REQUIRES a prerequisite.** Insights don't have a `column_name` field —
   it's embedded in title strings. Must add `column_name` to all 4 detectors' output
   format BEFORE deduplication can work. Title-based extraction is too fragile.

8. **Trend fix needs `datetime.fromisoformat()`.** Handles timezone-aware ISO strings
   from DatabaseService. Must sort by ordinal before regression. Growth rate units
   change from "per row" to "per day" — update recommendation text.

9. **3 NEW demo-breaking issues found:**
   - Vector DB empty on first run → agent has no schema context → nothing works
   - MongoDB + analyst mode → prompt says "use MongoDB syntax" but tools expect SQL
   - `sql=None` when agent completes without executing → crashes downstream at chat.py:357

---

### Phase 1: Demo-Ready (6 working days — revised from 5)

**Goal:** Eliminate crashes, false "no results", and nonsensical insights.
**Validated by:** 4 rounds of review (20 agents). Every fix verified against actual code, sequencing verified.

**Pre-work (Day 0):**
Before touching any production code, set up the validation infrastructure:
- Write failing regression tests for each Phase 1 fix (tests should FAIL on current code, PASS after fix)
- Add feature flags in config.py for risky changes (so we can toggle off if demo breaks)
- Create `/api/v1/health/diagnostic` endpoint that exposes fix-effectiveness metrics

| Day | What | How (Validated) | Files |
|-----|------|-----------------|-------|
| 0 | **Write regression tests FIRST** | Tests: masked success detection, column_name presence, date-based trends, smart ID cardinality. All must FAIL on current code. | `tests/test_phase1_fixes.py` (new) |
| 0 | **Add feature flags** | `ENABLE_JSON_ERROR_DETECTION`, `ENABLE_SUCCESS_FIELD_CHECK`, `ENABLE_COLUMN_NAME_FIELD`, `ENABLE_INSIGHT_DEDUPLICATION`, `ENABLE_DATE_BASED_TRENDS`, `ENABLE_SMART_ID_EXCLUSION`. Default: True. | `config.py` |
| 0 | **Diagnostic metrics endpoint** | Add Prometheus metrics: `error_masking_detections`, `circuit_breaker_activations`, `stale_cache_hits`. Expose via `/api/v1/health/diagnostic`. | `metrics.py`, `health.py` |
| 1a | **Fix error detection gate** (PRIMARY — must be first) | At react_agent.py:1503: ADD JSON parsing BEFORE string check. If `parsed.get("success", True) == False`, set `is_error = True`. Falls through safely for schema tools (plain text not JSON). **This must be done BEFORE the success-path fix or the success-path fix is ineffective.** | `react_agent.py` |
| 1b | **Fix success-path error masking** (SECONDARY — depends on 1a) | At react_agent.py lines 1594-1602 AND 1547-1555: AFTER parsing JSON, CHECK `execution_result["success"]` BEFORE returning status="complete". When False: append to `failed_attempts`, set status="error", DON'T reset counters. | `react_agent.py` |
| 1c | **Guard sql=None in downstream** (parallel to 1a/1b) | At chat.py:357: check `if not sql` before calling execute_query. Return error response instead of crash. | `chat.py` |
| 1 | **ToolRegistry: JSON-aware text path** (done 2026-04-16) | JSON strings route through 50KB path, not 10KB text slice. | `registry.py` |
| 1 | **Control-char recovery** (done 2026-04-16) | Strip control chars and retry parse before row_count=0 fallback. | `react_agent.py` |
| 2a | **Add `column_name` field to all 4 detectors** (PREREQUISITE) | `_detect_concentration`, `_detect_trends`, `_detect_anomalies`, `_detect_comparisons` each add explicit `column_name` key to every insight dict. **Must ship before 2b/2c or they break.** | `insight_detector.py` |
| 2b | **Deduplicate insights** (depends on 2a) | After all detectors run, deduplicate by `(type, column_name)` tuple, keeping highest-severity. Use `.get('column_name', 'unknown')` defensively for safety. | `insight_detector.py` |
| 2c | **Smart ID column exclusion** (parallel to 2b) | In `_get_numeric_columns()`: exclude columns matching `(?i)_id$\|^id$\|_pk$` ONLY IF cardinality == row count in first 100 rows. Keeps `region_id` (20 unique values). | `insight_detector.py` |
| 2c | **Fix trend detection time axis** (parallel to 2b) | Use `datetime.fromisoformat()` to parse date values to ordinal. Sort time_series by ordinal before regression. Skip if no date columns (don't fall back to row index — that's the bug). Update recommendation text: "per day" not "per row". | `insight_detector.py` |
| 3 | **Connection pool for checkpointer** (done 2026-04-16) | AsyncConnectionPool with check=check_connection. | `checkpointer.py` |
| 3 | **Fix cleanup SQL** (done 2026-04-16) | split_part(thread_id, ':', 1) for session join. | `cleanup_service.py` |
| 3 | **Stop blocking SQL comments** (done 2026-04-16) | Remove `--` and `/* */` from injection patterns. | `security.py`, `sql_validator.py` |
| 3 | **API compatibility audit** (NEW from review) | Audit every response format change. Ensure frontend handles both old and new shapes. Add deprecation flags where needed. | `chat.py`, frontend |
| 3 | **Cache invalidation endpoint** (NEW from review) | Add `POST /api/v1/cache/invalidate` for manual refresh. Wire to frontend "Refresh Schema" button. Prevents stale LLM/query cache during demo. | `cache_service.py`, API |
| 4 | **Increase AGENT_TOOL_TIMEOUT for data lakes** (moved from Day 3) | Detect db_type: transactional keep 30s, data lakes (bigquery, snowflake, athena, trino, databricks, redshift) get 300s. **Moved to Day 4 because timeout changes are asymmetric — safe to extend, dangerous to shorten. Test with smaller fixes first.** | `react_agent.py`, `config.py` |
| 4 | **Frontend: SSE reconnect with backoff** | On error/timeout, auto-retry (1s, 2s, 4s, max 3). | `frontend/src/utils/api.js` |
| 4 | **Frontend: Chart config validation** | Validate required fields before ECharts. "Chart unavailable" fallback. | `frontend/src/components/ChartView.vue` |
| 5 | **Config validator** (NEW from review) | Script that checks config before demo: VECTOR_DB_TYPE consistent with available DB, REDIS_URL set if multi-worker, DB connectivity works, LLM provider reachable, schema indexed in vector DB. | `scripts/validate_demo_config.py` (new) |
| 5 | **Demo pre-flight checklist** | Script verifies: (1) Vector DB has schema indexed, (2) DB connection works, (3) LLM responds, (4) test query returns data, (5) feature flags at expected values, (6) cache cleared. | `scripts/demo_preflight.sh` (new) |
| 5 | **Integration test matrix** | Test: empty table, 10 rows, 1000 rows, 10K rows, ID columns, date columns, no date columns, schema-qualified names, MongoDB (standard mode only), concurrent requests. Each must produce correct output without crashes. | Manual + `test_phase1_fixes.py` |

**Rollback Strategy:**

| Change | Rollback Risk | Mitigation |
|--------|--------------|------------|
| Error detection gate | SAFE | Just a new check, old code intact |
| Success-path fix | SAFE | Reverts to current behavior (bug) |
| `sql=None` guard | SAFE | Reverts to crash |
| `column_name` field | **NOT SAFE** | Cached insights become mixed-format after revert. Mitigation: (a) use defensive `.get('column_name', 'unknown')` in dedup, (b) bump session TTL to expire cached insights |
| Smart ID exclusion | SAFE | Reverts to old heuristic |
| Deduplication | SAFE | Reverts to showing dupes |
| Trend date axis | SAFE | Reverts to row-index (bug) |
| AGENT_TOOL_TIMEOUT | **ASYMMETRIC** | Safe to extend. If revert shortens, in-flight long queries get aborted. Mitigation: don't revert mid-day, wait for low traffic |

**Known limitations after Phase 1 (documented, not fixed):**
- MongoDB analyst mode generates MongoDB syntax but tools expect SQL (documented as unsupported; standard mode works)
- Concurrent requests to same session rejected with 5s timeout (documented: wait for previous to finish)
- Client disconnect holds lock for up to 10 minutes (mitigated by TTL, not fixed until Phase 2)
- Multi-tenancy is single-tenant per session (by design, not a gap)

### Phase 2: Production-Resilient (3-4 weeks — revised from 2-3)

**Goal:** Handle concurrent users, network failures, and data lake scale.
**Validated by:** Phase 2 feasibility review found each item has deeper complexity than originally estimated.

**State Machine Hardening:**

| What | Why | How (Validated) | Effort |
|------|-----|-----------------|--------|
| Deep-copy checkpoint on resume | In-place mutation race condition | **Selective deepcopy** of `state.values["messages"]` only (NOT entire state — contains asyncio locks and service refs that can't be deepcopied). Add async lock around read-modify-write. | 1-2 days |
| Complete state returns from all nodes | Actively broken: tool_node:1454 returns only `{"messages": []}`, tool_node:1749 returns only 3 fields | Create `_build_complete_state_update()` helper. Agent_node returns: messages, status, iteration, total_usage, consecutive_no_tools, iterations_without_execution, consecutive_failures. Tool_node returns: messages, failed_attempts, consecutive_failures, consecutive_no_tools, iterations_without_execution, status. | 2-3 days |
| Circuit breaker: **two counters** | Single counter conflates exploration with failure | Split into `iterations_without_sql_attempt` (exploration tools) and `sql_attempts_failed` (SQL execution failures). Trigger on either: exploration >= 10 OR SQL failures >= 3. | 1-2 days |
| Proper coroutine cancellation | `asyncio.wait_for` does NOT cancel the coroutine, just raises TimeoutError. Zombie queries keep running. | Use `asyncio.create_task()` + `asyncio.shield()` + explicit `task.cancel()` in timeout handler. Plus DB-type-specific timeouts from Phase 1 Day 4. | 1 day |

**Infrastructure Hardening:**

| What | Why | How (Validated) | Effort |
|------|-----|-----------------|--------|
| Distributed lock: fail loudly | Silent local fallback = no cross-worker safety | Remove local fallback in production. Add `settings.DEVELOPMENT_MODE` escape hatch so dev/test can run without Redis. Log CRITICAL if fallback triggers in prod. | 0.5 day |
| Health checks test real DB connectivity | Load balancer routes to dead DB | Iterate active sessions → get unique db_configs → call `pool_manager.health_check()` for each. Cache results for 10s to avoid hammering DBs. Include LLM provider ping. | 2-3 days |
| Graceful shutdown with drain | FastAPI lifespan doesn't support this natively | Custom middleware tracks active request count. Shutdown waits up to 30s for drain. Set 503 on new requests during drain. Handle SSE streams specially. | 1-2 days |
| Connection pool pre-flight check | Dead connections handed to callers | Add health check callback to asyncpg pool (same pattern as checkpointer fix done 2026-04-16). | 0.5 day |
| Lock extension as background task | Event-driven refresh in astream loop misses long tool executions | `asyncio.create_task()` that extends lock every 60s in background. Cancel on completion. | 0.5 day |

**Analysis Engine Quality:**

| What | Why | How (Validated) | Effort |
|------|-----|-----------------|--------|
| Unified ColumnClassifier | 5 copies of column detection with different behavior | Single `analysis_engines/column_classifier.py` classifying columns as numeric/categorical/date/ID/text. Must support BOTH raw and aggregated data (Phase 3 dependency). Requires Phase 1 `column_name` field prerequisite. | 3-4 days |
| NaN/Infinity sanitization at source | Serialization failures from analysis output | `sanitize_numeric()` called after EVERY statistical computation, not just at final output. | 1 day |
| LLM output sanitization | Control characters from LLM break JSON | Strip control chars immediately after LLM response, before any parsing. | 0.5 day |

**Frontend Resilience:**

| What | Why | How | Effort |
|------|-----|-----|--------|
| Virtual scrolling for tables | 1000+ row tables cause DOM lag | `vue-virtual-scroller` or equivalent. | 1-2 days |
| Proper error categorization | Generic "Stream disconnected" not actionable | Map backend error codes to user-friendly messages with retry guidance. | 1-2 days |
| InsightCard missing field handling | Missing title/recommendations causes broken cards | Default values for all optional fields. | 0.5 day |
| Conversation storage cleanup | localStorage 5MB quota exceeded for power users | Cap at last 5 conversations; strip execution_result rows before persist; add "clear history" button. | 1 day |

**Observability (NEW from review):**

| What | Why | How | Effort |
|------|-----|-----|--------|
| Fix-effectiveness metrics | Operators need to verify fixes work in production | Prometheus counters: error_masking_detections, circuit_breaker_activations, stale_cache_hits, session_violations. Expose via `/health/diagnostic`. | 1 day |
| Required OTEL telemetry | Currently optional (`OTEL_ENABLED=false` default) | Make OTEL required for production. Validate spans exist for LLM calls, DB queries, tool executions. | 1-2 days |
| Alert thresholds | Metrics emitted but no alerts | Prometheus alerting rules: P95 latency > 8s, error rate > 5%, circuit breaker state change. | 1 day |

### Phase 3a: Data Lake Foundation (2 weeks)

**Goal:** Enable long-running queries reliably.
**Validated by:** Phase 3 feasibility review found original Phase 3 estimate was 4-6 weeks but actual is 8-10 weeks. Split into 3a/3b/3c.

**Phase 3a is the REQUIRED foundation for Phase 3b/3c.** Blocks all other data lake work.

| What | Why | How | Effort |
|------|-----|-----|--------|
| **DB-type-specific timeouts** (critical path) | Global AGENT_TOOL_TIMEOUT=30s kills every data lake query. Phase 1 Day 4 addresses partially; 3a makes it complete and explicit per-DB. | `TOOL_TIMEOUT_BY_DB = {"postgresql": 30, "bigquery": 300, "snowflake": 300, ...}`. Apply at tool execution layer. | 2-3 days |
| **SSE heartbeat task** | Browser/proxy timeout during 5-min queries | Background asyncio task emits progress events every 15s while main task runs. Coordinated with lock extension task (Phase 2). | 3-4 days |
| **Aggregation detection** | Prerequisite for Phase 3c aggregated-mode insights | Add `aggregated: bool` and `grouping_columns: List[str]` to execution_result schema. Detect from SQL AST (if has GROUP BY) or column names (SUM/COUNT/AVG). | 2-3 days |

**Completion criteria for 3a:**
- Query times out at DB-appropriate limit (300s for data lakes), not 30s globally
- 5-minute query streams heartbeats without browser/lock disconnection
- Execution result correctly flags aggregated vs raw

### Phase 3b: Async Executors (3-4 weeks)

**Goal:** Optimize data lake query execution.
**Depends on:** Phase 3a (timeouts, heartbeats) complete.

| What | Why | How (Validated) | Effort |
|------|-----|-----------------|--------|
| **Pool manager: async-native support** | Current pool wraps all sync DBs in ThreadPoolExecutor — async executor in thread is counterproductive | Redesign pool to distinguish sync DBs (executor thread) vs async DBs (native asyncio). Add AsyncExecutorProtocol. | 1 week |
| **BigQuery async executor** | 80% of data lake usage | Use QueryJob polling pattern: `client.query() → poll job.state → fetch results`. Store query_id for cancellation. | 1-2 weeks |
| **Snowflake async executor** | Native `execute_async()` exists but not used | `execute_async()` returns query_id, poll with `get_query_status()`. Handle pyarrow result format. Connection context: same connection must poll and fetch. | 1 week |
| **Query progress events** | User needs feedback during 5-min waits | DB-specific: BigQuery provides `total_bytes_processed`, Snowflake provides only state, Athena/Trino provide nothing. Graceful UX fallback to elapsed time. | 1 week |

**Completion criteria for 3b:**
- BigQuery shows "X% complete (bytes scanned)"
- Snowflake shows "Executing... (elapsed: 2m 15s)"
- Timeout cancels actual query execution (not just Python task), no zombie queries accumulating cost

### Phase 3c: Analytics Excellence (2-3 weeks, Optional)

**Goal:** Cost awareness and aggregated-mode insights.
**Depends on:** Phase 3a aggregation detection complete.

| What | Why | How (Validated) | Effort | Risk |
|------|-----|-----------------|--------|------|
| **BigQuery cost estimation** | SELECT * on petabyte table = $5000+ | `QueryJobConfig(dry_run=True)` returns `total_bytes_processed`. Convert to $. Show in UI before execution. | 3-4 days | Low — API exists |
| **Cost estimation for others** | UX consistency across DBs | Athena/Snowflake/Trino have NO unified cost API. EXPLAIN gives rough row estimates. ±50% accuracy at best. | 1 week | **HIGH — frustrating UX** |
| **Aggregated-mode insight detection** | Insights from GROUP BY fundamentally differ from raw rows (not just simpler) | Read `aggregated` flag from execution result. Different z-score thresholds, different concentration baselines, skip trends with <5 groups. | 2 weeks | Medium — threshold recalibration |
| **System prompt: conditional GROUP BY** | LLM generates SELECT * by default; for aggregate questions, push to DB | Add conditional guidance: "For analytical questions with aggregation, prefer GROUP BY over SELECT *". Test breaks existing demo scenarios — update test data. | 2-3 days | Medium — breaks existing tests |

**NOT recommended for any Phase** (review finding: diminishing returns vs effort):
- Automatic two-phase queries (adds 100-300ms to EVERY query for marginal benefit on very large tables only)
- Full SQL transformation layer for multi-DB analytical functions (5+ weeks, fragile)
- Athena/Trino async (no native async driver, requires HTTP API work, 2+ weeks)
- Cost estimation for Athena/Snowflake/Trino (no unified API, ±50% accuracy = frustrating UX)

---

## Test Infrastructure Prerequisite (Required for Phase 2+)

**Status:** Zero integration tests exist for data lake databases. Cannot verify Phase 3 work without this.

**Required before starting Phase 3:**
- Docker Compose: BigQuery emulator, MinIO + Trino for Athena simulation, Snowflake Docker (if licensable)
- Mock long-running query pattern (sleep 5 min, emit progress)
- Test data generator: 1000 rows → GROUP BY versions for both modes
- CI integration: tests run in docker-compose per PR

**Effort:** 3-4 days setup, but unblocks all Phase 3 validation.

---

## Architecture: Current vs. Target

### Current (Fragile)
```
Tool returns JSON string
  -> ToolRegistry checks for "Error" literal (MISSES JSON errors)
  -> ToolRegistry text branch: 10KB truncation (BREAKS JSON)
    -> react_agent json.loads() (FAILS on broken JSON)
      -> fallback: success=True, row_count=0 (MASKS ERROR)
        -> consecutive_failures reset to 0 (BREAKS CIRCUIT BREAKER)
          -> user sees "no results" (WRONG)
```

### Target (Resilient)
```
Tool returns JSON string (contract preserved for LangChain ToolMessage)
  -> ToolRegistry detects JSON, routes through 50KB JSON path (no truncation)
    -> react_agent json.loads() succeeds
      -> tool_node PARSES success field from JSON (not string matching)
        -> on success=False: failed_attempts++, circuit breaker tracks it
          -> user sees actual error with guidance
        -> on success=True: normal flow, results displayed
```

---

## What Success Looks Like

**After Phase 1 (demo-ready):**
- No more "query returned no results" when data exists
- No more "policy_id trend 18865%" nonsense
- No more duplicate insights
- No more "connection is closed" crashes
- No more "suspicious patterns" false rejections
- SSE streams recover from network blips

**After Phase 2 (production-ready):**
- Handles concurrent users without state corruption
- Connection failures detected and recovered automatically
- Health checks accurately reflect system state
- Large datasets (10K+ rows) processed without memory issues
- Checkpoint resume works correctly after crashes

**After Phase 3 (excellence):**
- Insights are genuinely useful for business decisions
- Analytics work correctly across all database types
- Performance optimized for real-world data patterns

---

## Full Issue Inventory

### CRITICAL (11)

| # | Issue | Location |
|---|-------|----------|
| 1 | ToolRegistry slices JSON strings at 10KB, breaking parsing | registry.py:266-268 |
| 2 | Parse failures masked as success with row_count=0 | react_agent.py:1608-1614 |
| 3 | execute_sql parse failure masked as success | react_agent.py:1542-1545 |
| 4 | execute_and_analyze empty result masks upstream errors | query_tools.py:644 |
| 5 | execute_sql empty result masks executor errors | query_tools.py:169 |
| 6 | Checkpoint resume mutates state in-place | react_agent.py:2635 |
| 7 | Message truncation breaks tool call/result pairing | react_agent.py:1315 |
| 8 | Distributed lock silently falls back to local | distributed_lock.py:206-254 |
| 9 | Health checks return hardcoded "healthy" | health.py:136-145 |
| 10 | ID columns treated as business metrics | insight_detector.py:76-79 |
| 11 | Row index used as time axis for trends | insight_detector.py:165-235 |

### HIGH (18)

| # | Issue | Location |
|---|-------|----------|
| 1 | Circuit breaker counters reset on masked success | react_agent.py:1645 |
| 2 | Status forced to "complete" on parse error | react_agent.py:1644 |
| 3 | Tool timeout doesn't cancel coroutine | react_agent.py:1493 |
| 4 | Incomplete state returns from tool_node | react_agent.py:1454 |
| 5 | consecutive_failures not reset when agent recovers | react_agent.py:1399 |
| 6 | Lock extension is event-driven, not background | react_agent.py:2975 |
| 7 | Lock TTL (120s) shorter than agent timeout | distributed_lock.py:35 |
| 8 | Connection pool cleanup races with in-flight queries | connection_pool_manager.py:797 |
| 9 | No graceful shutdown draining | main.py:284-324 |
| 10 | No connection health check before handing out pool | connection_pool_manager.py:620 |
| 11 | Partial startup on service failure (app runs degraded) | main.py:131-282 |
| 12 | No insight deduplication across detectors | insight_detector.py:40-61 |
| 13 | LLM control chars not sanitized before JSON parse | query_tools.py:543 |
| 14 | Chart config can reference non-existent columns | chart_intelligence.py:223 |
| 15 | No SSE auto-reconnect on network failure | frontend/src/utils/api.js |
| 16 | No chart config validation or fallback UI | frontend/src/components/ChartView.vue |
| 17 | No virtual scrolling for large result tables | frontend/src/components/results/ResultsTable.vue |
| 18 | Silent JSON event dropping in SSE stream | frontend/src/utils/api.js |
