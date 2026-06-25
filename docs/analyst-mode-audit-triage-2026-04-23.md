# Analyst Mode Audit — Triage + Mitigation Plan (2026-04-23)

**Input**: `docs/analyst-mode-deep-audit-2026-04-22.md` — 20 findings, 7 addressed in commits `07e3ba4` + `0f6a6cc`, **13 deferred**.

**Method**: Deep-research pass on the 13 deferred items (2 parallel Explore agents plus direct verification) to re-check accuracy, surface hidden complexity, and sequence fixes by dependency / risk / value.

**This doc is a plan, not code.** No implementation until the user approves the sequencing below.

---

## What changed after deep research

Three corrections to the original audit that affect priority:

1. **#10 PII exposure upgraded P1 → P0**. `is_pii` is actively populated across ≥5 code paths in `data_dictionary.py`; blast radius is narrow (only `get_sample_data` leaks raw rows, confirmed); redaction pattern `[REDACTED]` is consistent with the existing `ErrorSanitizer` style. This is a production hazard, not a cleanup item.
2. **#8 cache observability is nearly free**. The full telemetry stack is already deployed: OpenTelemetry + OTLP gRPC at `backend/app/core/telemetry.py:34-105`, Prometheus counters at `backend/app/api/metrics.py:34-161` (including `llm_cache_operations` + `db_cache_operations`), structlog at `backend/app/core/logging_config.py:15-96`, and endpoints `/metrics`, `/metrics/detailed`, `/health/diagnostic`, `/health/detailed` all live. Gap is **purely instrumentation absence** at the cache-tool boundary — ~15 min of structured-log additions for Phase 1.
3. **#11 scope tightened**. Dropping `tool_calls_count` from `ChatResponse` breaks `test_models_middleware_validators.py:610` (asserts `resp.tool_calls_count == 0`). Drop requires a 1-line test update. Not a blocker — just a coupled edit.

---

## Re-prioritised rollup

| # | Gap | Original | **Updated** | Effort | Wave | Bundle with |
|---|---|---|---|---|---|---|
| 10 | PII exposure via `get_sample_data` | P1 | **P0** | S | **1** | — |
| 8 | Cache observability — Phase 1 (logs) | P1 | P1 | S | **1** | G-Phase-1 |
| 12 | `key_findings` ↔ `insights` duplicate source | P1 | P1 | S | **1** | — |
| 19 | `_CRITICAL_STATE_FIELDS` drift risk | P2 | P2 | S | **1** | #18 |
| 18 | `consecutive_no_tools` ghost routing signal | P2 | P2 | S | **1** | #19 |
| 20 | `annotate_chart` discovery monitoring | P2 | P2 | S | **1** | — |
| 9 | `get_cached_rows` silent limit cap | P1 | P2 | S | **1** | — |
| 15 | Sampling disclaimers pollute insights list | P2 | P2 | S | **1** | — |
| 5 | NoSQL partition-key live-metadata fallback | P0 | P1 | M | **2** | #17 |
| 17 | Stale schema auto-invalidate on error | P2 | P1 | M | **2** | #5 |
| 13 | Agent wall-clock soft budget | P1 | P1 | M | **2** | — |
| 11 | Waste fields (`tool_calls_count` etc.) | P1 | P2 | S | **2** | — |
| 16 | `inspect_cached_result` missing ops | P2 | P2 | L | **3** | — |
| G | Prompt caching rollout | — | — | varies | **2/3** | #8 |

**Legend**: S = ≤1 hour, M = half-day, L = 1+ day. Wave 1 = ship this week (all S, low risk). Wave 2 = next sprint (M, some design). Wave 3 = RFC first.

---

## Wave 1 — Ship this week (8 items, all S, low risk)

Surgical, testable, reversible. Each has a clear validation path. Target: single PR, bundled if small enough; else split into logical commits.

### 1. PII masking in `get_sample_data` (#10) — **P0**

**File**: `backend/app/services/tools/query_tools.py:1394-1480` (handler body), `backend/app/services/data_dictionary.py` (column descriptions producer).

**What**: In the handler, load `ColumnDescription` rows for the target table via the existing `data_dictionary` service. For any column where `is_pii=True`, replace cell values in the returned rows with the literal string `[REDACTED]`. Preserve row count and column order. If no description exists for a column, fall back to a name heuristic (`email`, `password`, `ssn`, `phone`, `address`, `credit_card`, `secret`, `token`, `api_key`) — conservative mask, rather than leak.

**Why `[REDACTED]`**: existing `ErrorSanitizer` at `security.py:282-328` already uses this literal — code-style consistency.

**Validation**:
- New pytest: create a mock table with `is_pii=True` on one column; call `get_sample_data`; assert the column's cells are `[REDACTED]` and other columns pass through untouched.
- New pytest: no description; column name matches heuristic; assert masked.
- Regression pytest: `is_pii=False`; assert cell value preserved verbatim.

**Risk**: Over-masking a column named "username" (common but not actually PII). Mitigation — the name heuristic is only a fallback when NO description exists. Once the dictionary is populated, explicit `is_pii=False` suppresses the heuristic.

---

### 2. Cache observability Phase 1 — log-only (#8)

**Files**: `backend/app/services/result_cache.py`, `backend/app/services/tools/cache_inspection_tools.py`.

**What**: Add ~20 lines of structlog field-structured log entries at 5 specific points:
- `cache_inspection_tools.py:get_cached_rows()` — emit `"get_cached_rows.complete"` with `rows_ref`, `offset`, `limit`, `hit`, `latency_ms`, `rows_returned`.
- `cache_inspection_tools.py:inspect_cached_result()` — `"inspect_cached_result.complete"` with `rows_ref`, `operation`, `hit`, `latency_ms`, `result_rows`.
- `result_cache.py:get_rows_slice()` — `"cache.slice"` with `rows_ref`, `offset`, `limit`, `hit`, `latency_ms`, `total_rows` on hit.
- `result_cache.py:astore()` — elevate the existing timeout error log to a structured log line with `operation="astore.timeout"`, `rows_ref`, `row_count`, `latency_ms`.
- `query_tools.py:execute_and_analyze()` around line 1164 — structured log `"cache.store.executed"` with `rows_ref`, `row_count`, `success`.

**Why logs, not metrics, for Phase 1**: structlog + JSON output + existing log aggregation path is already live. Operators can grep/filter immediately. Prometheus counters (Phase 2, Wave 2 or later) only pay off if real-time dashboards are needed.

**Validation**:
- Start dev stack, run one analyst query, run one follow-up question that should hit the cache, one that shouldn't.
- `docker logs backend | grep cache.slice` — verify one `hit=true` and one `hit=false` line emitted.
- No assertion test (logs are observability, not contracts); a smoke-run is the test.

**Risk**: None. Additive, no behaviour change.

---

### 3. `key_findings` ↔ `insights` unification (#12)

**File**: `backend/app/api/chat.py` — two literally-duplicated 11-line blocks at `411-421` (non-streaming) and `862-872` (streaming).

**What**: Extract a module-level helper `_flatten_insights_to_key_findings(insights: List[Dict]) -> List[str]` and call it from both sites. Pure refactor — no behaviour change.

**Validation**:
- `npm run build` (no-op for backend but routine), `ast.parse` on `chat.py`.
- Targeted pytest: `_flatten_insights_to_key_findings([{"severity": "high", "description": "foo"}])` → `["[HIGH] foo"]`. Edge cases: missing severity, missing description, >5 insights truncates.
- Regression check: existing smoke tests that assert on `key_findings` shape still pass.

**Risk**: Near-zero — pure deduplication.

---

### 4. `_CRITICAL_STATE_FIELDS` drift test (#19)

**File**: `backend/app/services/react_agent.py:1405-1411` (the tuple), tests directory.

**What**: Add a pytest that reflects on the `ReActState` TypedDict's fields and asserts every field named in `_CRITICAL_STATE_FIELDS` exists in the state. Locks the invariant so future additions don't silently drift.

```python
def test_critical_state_fields_match_schema():
    from app.services.react_agent import ReActState, ReActAgentNodes
    state_fields = set(ReActState.__annotations__.keys())
    for field in ReActAgentNodes._CRITICAL_STATE_FIELDS:
        assert field in state_fields, f"_CRITICAL_STATE_FIELDS lists '{field}' but ReActState has no such field"
```

**Validation**: pytest run. Should pass today; will fail when someone adds/removes a field without updating the tuple.

**Risk**: None.

---

### 5. `consecutive_no_tools` routing wire-up (#18)

**File**: `backend/app/services/react_agent.py:271` (state field), `1599-1611` (local termination), `2790-2926` (should_continue router).

**What**: **Decision**: wire into `should_continue()` as a redundant safety net, rather than remove. The field already does useful work at `agent_node` line 1599-1611 (early-terminate on 2 no-tool responses); surfacing the same signal to the global router makes the termination condition visible to everyone reading `should_continue()`.

Concretely: add a clause in `should_continue()` that returns `"end"` when `state.get("consecutive_no_tools", 0) >= 2` AND `state.get("status") != "complete"`. Guard against conflict with the `max_iterations` check.

**Validation**: extend existing `should_continue` test to cover the new branch. Regression test — run existing pytest suite.

**Risk**: Low. If the added clause is miswritten, worst case is premature termination. Mitigated by the existing max_iterations cap catching everything.

---

### 6. `annotate_chart` invocation monitoring log (#20)

**File**: `backend/app/services/tools/analysis_tools.py:467` (annotate_chart handler).

**What**: Add a single `logger.info("annotate_chart.invoked", chart_type=..., insights_count=..., statistics_present=bool(...))` at the top of the handler. No behavioural change — just a signal we can grep production logs for to confirm the LLM is still discovering the tool after the prompt-diet's removal of prescriptive guidance.

**Validation**: smoke run — issue an analyst question that triggers chart annotation, confirm log line.

**Risk**: None.

---

### 7. `get_cached_rows` silent-cap signal (#9)

**File**: `backend/app/services/tools/cache_inspection_tools.py:38, 85-91, 104-112`.

**What**: Add `requested_limit` and `actual_limit` to the returned dict (alongside existing `limit`). When they differ, also add `"limit_capped_reason": "max_50_per_call"` so the LLM sees an explicit signal and can pivot to `top_n` or `group_summary` for larger analytical slices.

**Validation**: pytest — call `get_cached_rows(rows_ref, offset=0, limit=1000)` → assert `requested_limit=1000, actual_limit=50, limit_capped_reason` present.

**Risk**: None. Additive.

---

### 8. Sampling disclaimer out of `insights` (#15)

**File**: `backend/app/services/tools/query_tools.py:1109-1140, 1206-1232` (response build site).

**What**: Move the sampling disclaimer insight construction out of the `insights` list. Add a top-level `sampling_used: {used: bool, sample_size: int, total_rows: int, warnings: [...], recommendation: str}` field on the response. Update the frontend's `AIResponseCard.vue` + `InsightCard.vue` to render sampling info in its own spot (new `.sampling-notice` component section or reuse `DataQualityIndicator` pattern).

**Validation**: pytest — `execute_and_analyze` with sampled result → assert `sampling_used.used=True`, `len(insights) == N` (no disclaimer card polluting the count). Frontend smoke — check a sampled query visually.

**Risk**: Small UI re-render. Need to ensure the frontend fallback path (old backend without `sampling_used` field) doesn't break — default render when `sampling_used` is `null` should be a no-op.

---

### Wave 1 summary

**Bundling options**:
- **Commit A**: #10 (PII) — standalone, security-sensitive, own PR.
- **Commit B**: #8 + #2 + #20 + #9 + #15 — "analyst-mode observability & response cleanup" — these all touch query_tools / cache_inspection / response shape. Single coherent commit.
- **Commit C**: #12 — `chat.py` refactor. Standalone.
- **Commit D**: #18 + #19 — react_agent.py hygiene. Standalone.

Total: ~4 commits, ship as one PR. Full backend pytest + frontend build + lint gate.

---

## Wave 2 — Next sprint (4 items, M, light design)

### 1. NoSQL partition-key live-metadata fallback (#5) + Stale schema auto-invalidate (#17) — bundled

**Why bundle**: both require a "refresh schema for table X" primitive. Ship the primitive once, consume from both paths.

**Files**:
- `backend/app/services/tools/schema_tools.py:get_table_schema()` (#5 consumer)
- `backend/app/services/react_agent.py:668-679` (#17 consumer — column-not-found error handler)
- `backend/app/services/distributed_lock.py:527-541` (existing lock primitive, reuse)
- `backend/app/services/vector_db.py` (indexing path)

**Design decision needed**:
- **For #5**: live-DB metadata reads — Cassandra `SELECT * FROM system_schema.columns WHERE keyspace_name=... AND table_name=...`, DynamoDB `DescribeTable` API call. Add new methods on the executor classes; guard with a capability check (not all backends support live metadata).
- **For #17**: on column-not-found error, tag the error with `{"stale_schema_suspected": True, "table": "...", "column": "..."}` and fire a background task that invokes the existing `schema_refresh_lock()` flow for that table only (not a full reindex).

**Validation**: integration-style test — seed Cassandra with a known partition key; artificially drop it from the vector-DB entry; call `get_table_schema`; assert live-metadata fallback fills in the gap. For #17, use the simulated column-not-found error path and assert the background refresh was triggered.

**Risk**: Medium. Live DB metadata reads may be slow for some backends (Snowflake `INFORMATION_SCHEMA` is notoriously slow). Guard with a 5-second timeout and fall through to the existing recovery hint if the live read doesn't return in time.

**Effort**: M (half-day). Small primitive + two consumers.

---

### 2. Agent wall-clock soft budget (#13)

**File**: `backend/app/services/react_agent.py:2790-2926` (should_continue), state schema.

**What**: Add `wall_clock_budget_seconds: int` and `wall_clock_start: float` to state. In `should_continue`, return `"end"` when `time.monotonic() - wall_clock_start > budget`. Default budget: 180 seconds (3 min — comfortably above a typical query but below the 50-min worst case).

**Validation**: unit test — mock a slow tool call, assert `should_continue` returns `"end"` when cumulative time exceeds budget.

**Risk**: Low. The cap is a safety net, not a correctness constraint. Existing `max_iterations` already catches many cases.

**Effort**: M. State schema change + test updates + `_CRITICAL_STATE_FIELDS` update.

---

### 3. Waste-field cleanup (#11)

**Files**: `backend/app/models/chat_models.py:160-169` (drop the 3 fields), `backend/app/api/chat.py:637, 640, 641, 653, 655, 1082` (drop from producers), `backend/tests/test_models_middleware_validators.py:610` (update assert).

**What**: Drop `tool_calls_count`, `execution_time_ms`, `usage` from `ChatResponse`. Update the 4 producer sites. Update the 1 test assertion.

**Validation**: pytest suite full run. Frontend `npm run build` (no-op expected — `usage` was never read; other two confirmed unused).

**Risk**: Low but real — there may be external consumers (audit logs, external dashboards) that I haven't discovered. Before merging, grep the full org (not just this repo) for `tool_calls_count`. If any external reader exists, deprecate with a `@deprecated` marker for one release before removal.

**Effort**: S if no external consumer, M if deprecation dance required.

---

### 4. Prompt caching Phase 1 — observability only (G)

**File**: `backend/app/services/llm_service.py:270` (`LLMUsageData`), `428-475` (call site).

**What**: Extend `LLMUsageData` with `cache_creation_input_tokens: int` and `cache_read_input_tokens: int`. Populate from `response.usage` attributes returned by LiteLLM for Anthropic models. Log a structured line when `cache_read_input_tokens > 0`. NO `cache_control` markers injected yet — just instrumentation.

**Rationale**: mirrors Wave 1 item #2 pattern. If the LLM provider is returning cache-read metrics (some already implicit-cache for prompts >1024 tokens without markers), we'll see the baseline before deciding if Phase 2 (explicit `cache_control` injection) is worthwhile.

**Validation**: pytest with a mock LiteLLM response that includes cache tokens → assert they populate into `LLMUsageData`. Smoke run in dev → grep logs for cache-read signals.

**Risk**: None. Pure observability.

**Effort**: S.

---

## Wave 3 — Design first (2 items)

### 1. `inspect_cached_result` missing operations (#16)

**Scope**: pivot / crosstab / correlate / regex-match / multi-column sort.

**Why RFC first**: this is feature work, not a fix. Need to decide:
- Which ops genuinely unblock analyst follow-ups vs which sound nice but are rarely asked?
- Output size caps per op (pivot can explode to 2D grid)?
- API shape — extend the existing `operation: str` + `params: dict` contract or introduce a new method?

**Action**: open an issue / design doc, gather 2-3 real follow-up questions from recent analyst sessions that would benefit, then scope the ops list. Do NOT implement until scope is frozen.

**Effort**: L (1-2 days once scope is decided).

---

### 2. Prompt caching Phase 2 + 3 (G)

**Gated on**: Phase 1 observability (Wave 2 item 4) producing at least one week of baseline data.

**Phase 2** (canary, 5-10% traffic): inject `cache_control: {type: "ephemeral"}` on the system message for Anthropic models behind `ENABLE_PROMPT_CACHING` flag. Optionally move `db_type_section` from prepend to append so the stable-prefix cache region is contiguous.

**Phase 3** (GA): flip flag to 100%, optionally restructure prompt assembly.

**Effort**: M per phase. Gate on concrete metrics (≥50% cache hit rate on turn 2+ with zero error-rate regression).

---

## Sequencing rationale

1. **Wave 1 first** because: every item is S, independently testable, and either additive or a near-pure refactor. Ships real value (PII fix alone is worth shipping) and establishes observability (#8) that lets us measure Wave 2's impact.
2. **Wave 2 after Wave 1 ships + cache observability has at least a few days of data** — we'll know if the Phase 2 rollout is worth the design effort.
3. **Wave 3 last** because #16 is feature work and should come from user-validated scope, not speculation.

**Bundling to reduce PR churn**:
- Wave 1 can ship as **one PR with 4 commits** (security-only, observability-and-cleanup, refactor, agent-hygiene). Easier to bisect than one monster commit.
- Wave 2's #5+#17 bundle into one PR; #13 separate; #11 separate (pending deprecation check); G-Phase-1 separate.

**Dependency graph** (explicit):

```
#10 (PII) ──────── no deps
#8 (obs logs) ──── no deps, unblocks monitoring of all others
#12 (refactor) ─── no deps
#19 (state test) ─ no deps
#18 (route wire) ─ loose pair with #19
#20 (chart log) ── no deps
#9 (limit signal) ─ no deps
#15 (sampling) ──── no deps

#5 (NoSQL live) ── bundled with #17 (schema primitive)
#17 (stale auto) ── bundled with #5
#13 (wall budget) ─ no deps, but depends on #19 landing (to keep _CRITICAL_STATE_FIELDS test current)
#11 (waste fields) ─ depends on external-consumer check
G-Phase-1 (LLM cache obs) ─ mirrors #8 pattern, can share commit or follow

#16 (new ops) ──── gated on user-validated scope
G-Phase-2/3 ──── gated on G-Phase-1 baseline
```

---

## Validation strategy per wave

### Wave 1 acceptance criteria
- [ ] All backend unit tests pass (`pytest` from `backend/` with real venv)
- [ ] `npm run lint` and `npm run build` on frontend — zero new warnings
- [ ] Smoke test in dev UI: run 2 queries, observe new log lines in `docker logs`
- [ ] For #10: manual test — table containing a known PII column (e.g. `users.email`) returns `[REDACTED]`
- [ ] For #15: sampled query renders disclaimer in its own section, insights list shows only real findings
- [ ] `_CRITICAL_STATE_FIELDS` test passes in pytest
- [ ] Update the 2026-04-22 audit doc with resolved markers for each item

### Wave 2 acceptance criteria
- [ ] Integration test for #5 live-metadata fallback (requires a Cassandra / DynamoDB test fixture)
- [ ] #17 auto-refresh fires on a simulated column-not-found error, completes in <5s
- [ ] #13 wall-clock budget cap verified in unit test
- [ ] Production log monitoring (via Wave 1 #8) shows no new error patterns in the week following rollout
- [ ] G-Phase-1 — at least one `cache_read_input_tokens > 0` log line in production

### Wave 3 acceptance criteria
- [ ] #16 — design RFC approved, scope frozen
- [ ] G-Phase-2 — canary ≥50% cache hit on turn 2+, zero error-rate regression, 1 week of data before Phase 3

---

## Risks and mitigations

1. **Over-masking in #10**: conservative name heuristic masks a column named "username" when it isn't PII. **Mitigation**: heuristic is a fallback ONLY when no column description exists. Once the dictionary is populated, `is_pii=False` suppresses it explicitly.
2. **External consumer of waste fields (#11)**: audit logs, dashboards outside this repo may read `tool_calls_count`. **Mitigation**: grep across the org before dropping; if any consumer, deprecate with one-release transition.
3. **Live metadata reads are slow (#5)**: Snowflake `INFORMATION_SCHEMA` is notoriously slow. **Mitigation**: 5-second timeout on the fallback; return the original error if timeout exceeded.
4. **Log volume from #8**: structured logs at every cache operation × analyst traffic = log bill. **Mitigation**: sample at 10% for the first week, bump to 100% if the cost is tolerable.
5. **#15 breaks frontend rendering if sampled-run response doesn't match new shape**: **Mitigation**: feature-flag the new shape; frontend reads both old and new for one release.

---

## What to update as we go

Each wave that ships should:
1. Add a **"Resolved in"** marker against the corresponding gap in `docs/analyst-mode-deep-audit-2026-04-22.md` with the commit SHA and date.
2. Add a **one-line entry** in root `CLAUDE.md`'s "Recent architecture decisions" section (keep the list pruned to the last 3-4 months).
3. Create a per-wave summary in `docs/analyst-mode-audit-wave-N-YYYY-MM-DD.md` so future sessions know which findings are live vs closed.

After all three waves, the 2026-04-22 audit doc should have every gap annotated with a resolution status; at that point, archive it (move to `docs/archive/`) and close the thread.

---

## Open questions for the user before starting Wave 1

1. **PII fallback heuristic** — include it (mask names like `email`, `ssn`) or only mask on explicit `is_pii=True`? Recommendation: include, for defense-in-depth.
2. **Log sampling for #8** — 10% initial sample or 100% from day one? Recommendation: 100% for the first week to establish baseline, then sample if volume justifies.
3. **Waste-field deprecation** — OK to drop cleanly in Wave 2, or do we need a deprecation cycle? Recommendation: full org grep first; if clean, drop; if not, deprecate.
4. **Wave 1 PR shape** — one PR with 4 commits, or 4 small PRs? Recommendation: one PR (4 commits) — cleaner review, single CI cycle, still bisectable.
