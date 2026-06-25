# Analyst Mode Deep Audit — 2026-04-22

**Scope**: Full-stack technical audit of the "talk to your data" analyst mode to find gaps that could break the end goal (real business insights, not mechanical stat dumps).

**Method**: 7 parallel audit agents (A–G), evidence-only reports with file:line citations. This doc is a synthesis, not a proposal — fixes are *described*, not implemented.

**Branch audited**: `fix/analyst-mode-reliability` (commit ancestor of the prompt-diet change applied 2026-04-22).

---

## Executive Summary

| Slice | Verdict | Top risk |
|---|---|---|
| A — ReAct Graph | ✅ Sound | `consecutive_no_tools` routing field is fragmented (set, locally read, never consulted by global router) |
| B — Tool Catalog | ✅ Clean | `annotate_chart` description has no concrete trigger; `question=` param not schema-required |
| C — `execute_and_analyze` internals | ⚠️ Silent-degradation risks | LLM narrator silently skipped when LLM config absent; error strings leak internals to LLM; sampling warnings diluting insights |
| D — Result cache | ✅ Hardened, 🚨 blind | IDOR defenses intact, but zero observability on hit rate → silent regression blind-spot |
| E — Schema / dictionary | ⚠️ NoSQL partition coverage conditional | Partition keys only returned when vector-DB indexed them; PII masking not wired to `is_pii` flag |
| F — Response / frontend | ⚠️ Waste + silent voids | 5 waste fields (produced, never consumed); empty insights render a silent blank section; confidence produced but never displayed |
| G — Prompt caching | 📋 Plan ready | Zero caching today; clean 3-phase rollout designed; ~81% projected cost reduction on Anthropic |

**Overall**: The analyst-mode skeleton is sound. The mission-threatening issues are all of one pattern: **silent degradation paths** that succeed with degraded output and give the operator no signal. Fix those and the system is robust.

---

## Findings by slice

### A. ReAct graph + control flow

**File**: `backend/app/services/react_agent.py`

- **Graph shape**: Two nodes (`agent` at line 2962, `tools` at 2963), entry point `agent` (2966). `agent` → `should_continue()` (conditional, 2790–2926) → `tools | agent | end`. `tools` → `agent` unconditional (2980).
- **Termination conditions (all covered)**: iteration cap (default 10, line 2799), 3+ permanent errors (2820), repeated identical error ×2 (2830), 5+ consecutive transient failures (2855), 3+ SQL failures (2881), 10/7 iterations without execution (2897–2912), last-message has no `tool_calls` (2918–2919). No unreachable paths detected.
- **Error handling**: Every tool error surfaced to the LLM as a `ToolMessage` (1739, 1787, 2087, 2137). No silent swallow; no retry; enhanced recovery hints appended at line 2124.
- **Tool timeout**: `TOOL_EXECUTION_TIMEOUT` (line 84, default 30s) with per-DB overrides via `TOOL_TIMEOUT_BY_DB` (112), applied via `asyncio.wait_for` at 1722.
- **Dead code**: None — every method instantiated and called. Flag-gated paths (`FIX_*`) are deliberate rollback branches.

**State-schema drift** (noted, not critical):
- `consecutive_no_tools` (line 271) is written in `agent_node` and locally read at 1599–1606 (local-terminate on 2 no-tool responses), but **never inspected by the global router** `should_continue()`. Redundancy with iteration cap makes this a P2.
- `_CRITICAL_STATE_FIELDS` tuple (1405–1411) is manually maintained. Future state additions that forget this list will silently carry stale values across early-return paths.

**Top 3 risks from this slice**:
- **P2** Fragmented routing signal — `consecutive_no_tools` is a "ghost" field from the router's perspective.
- **P1** No per-iteration soft budget — a slow 5-min query × 10 iterations = 50 min wall-clock worst case. The circuit breaker eventually fires; UX suffers first.
- **P2** Implicit `_CRITICAL_STATE_FIELDS` coupling risks future silent bugs when someone adds a routing field but forgets the tuple.

---

### B. Tool catalog

**Files**: `backend/app/services/tools/{definitions.py, analysis_definitions.py}`, bindings in `react_agent.py:289–635`.

- **Inventory**: **18 tools**, all defined, bound, and implemented. No orphans, no `NotImplementedError` stubs. (Full table in Audit B raw output; spot-check showed 100% coverage.)
- **Handler coupling**: All schemas match handler signatures exactly. No divergences.
- **Duplication check**: `execute_sql` vs `execute_and_analyze`, `get_cached_rows` vs `inspect_cached_result`, `get_sample_data` vs `get_table_schema` — all three pairs have clear distinctions in their descriptions.
- **Phase 4.2 cache-tool binding verified held** at `react_agent.py:443–490` — the prior bug where `get_cached_rows` / `inspect_cached_result` were registered in the ToolRegistry but not bound to LangGraph is fixed.

**Description quality for the 7 specialist tools no longer named in SYSTEM_PROMPT** (post-diet):

| Tool | Rating | Notes |
|---|---|---|
| `detect_insights` | ADEQUATE | "AFTER executing SQL" + 4 concrete scenarios |
| `analyze_statistics` | ADEQUATE | Names 4 user-facing triggers |
| `check_data_quality` | ADEQUATE | "BEFORE making strong claims" |
| `compare_periods` | ADEQUATE | MoM/YoY/QoQ triggers named |
| `suggest_followups` | ADEQUATE | Chains from insights, 4 insight types listed |
| `recommend_chart` | ADEQUATE | Explicit sequencing guidance |
| `prepare_chart_data` | ADEQUATE | Chains from `recommend_chart` |
| `annotate_chart` | **WEAK** | `analysis_definitions.py:366-373` states intent ("to make charts self-explanatory") but **no concrete user trigger phrase** — LLM may skip it |

**`question=` on `execute_and_analyze`**: schema at `definitions.py:248` has `required: ["sql"]` — `question` is **optional in the schema**, relying on description + prompt guidance for compliance. Not a regression from the prompt diet; pre-existing condition.

**Top 3 risks**:
- **P0** `annotate_chart` has no autonomous discovery signal. Fix: prepend description with "Use when you have insights or statistics to highlight visually; after `prepare_chart_data`; when trends or outliers are detected".
- **P0** `question=` should be marked `required: ["sql", "question"]` in schema. Cheap, eliminates reliance on prompt compliance. (Covered again in slice C.)
- **P1** Cache-tool discovery works because SYSTEM_PROMPT explicitly names them and has the ROUTING RULE; if the prompt were further trimmed, they'd slip. Watch for regression.

---

### C. `execute_and_analyze` internals

**File**: `backend/app/services/tools/query_tools.py:730–1321`

**End-to-end path verified (19 steps)** — covers dialect routing, row-limit enforcement, memory guard (50MB), sampling logic, string truncation (500 chars), stat computation, parallel analysis engines, LLM narrative, sampling-disclaimer insert, result-cache write, response build.

**`question=` threading** (commit 2ac079b): param enters at `react_agent.py:409` → `ToolRegistry.execute(..., question=question)` (421) → handler at `query_tools.py:734` → `enhance_insights_with_llm(..., question=question)` at 1090. If `question` is empty, fallback prompt at 591–596 anchors the narrator on "most important findings in the data" (generic output).

**Insights are BOTH rule-based AND LLM-generated, stacked** (line 719: `enhanced = llm_insights + existing_insights`). LLM findings prepend for first-card priority. The fallback from commit 046adc4 is legitimate graceful degradation — not masking a bug.

**Mission-threatening gaps found**:

- **P0** **LLM enhancement silently skips when no LLM config** (line 652–658). The tool still returns `{"success": True, "insights": [...]}` populated only with rule-based findings. Agent has no signal the narrator was skipped. Analyst's "business narrative" silently downgrades to stat descriptions. Fix: return `"narrator_status": "skipped_no_llm_config"` and flag `"insights_type": "statistical_only"`.
- **P1** **Error strings leak raw exception text to the LLM** at lines 1306–1321 (`{"success": False, "error": str(e), "message": f"Analysis failed: {str(e)}"}`). Includes DB errors, stack fragments, LLM timeouts. The LLM sees these via `ToolMessage` and can accidentally emit them despite the SYSTEM_PROMPT "never mention internals" voice rule. Fix: sanitize via existing `ErrorSanitizer.sanitize_error()` from `security.py` before constructing the error payload.
- **P1** **Chart spec is None without signal** (line 1222: `"chart": chart_recommendation`). Frontend can't distinguish "not chartable" from "chart recommender failed". Fix: add `"chart_possible": bool` with explicit rationale when None.
- **P2** **`question=` missing has no log/signal** — agent is allowed to omit it, and the fallback fires silently. Fix: log INFO when `question` is blank/missing; optionally include `"question_available": bool` in response for frontend diagnostics.
- **P2** **Sampling disclaimers pollute the insights list** (1109–1140). Meta-commentary ("Pattern detection based on random sample...") competes with real business findings in the UI. Fix: move to `response["sampling_used"] = {...}` as a top-level field; keep `insights` pure.

**No silent drops** confirmed — sampling, truncation, caching are all signaled in the response (`limit_applied`, `has_more`, `message`, `rows_truncated`, `rows_truncated_reason`).

---

### D. Result cache + rows_ref lifecycle

**File**: `backend/app/services/result_cache.py`; handlers at `backend/app/services/tools/cache_inspection_tools.py`.

- **Backend**: Redis-first with in-memory LRU fallback. 2s connect timeout, 5s socket timeout, 10s `astore` wait_for (line 281–305). Graceful degradation on Redis unavailability.
- **TTL**: 1800s (30 min) via `settings.RESULT_CACHE_TTL_SECONDS`.
- **Memory cap**: 200 entries, LRU evict (line 58–60).
- **NaN/Inf scrubbing**: confirmed at `result_cache.py:63–82, 118–128`; test `test_phase4_fixes.py:1456–1485` passing.
- **IDOR hardening (commit 1adce34) held** ✅ — two defenses:
  - Export endpoint: `queries.py:630–656` with `hmac.compare_digest` on rows_ref prefix vs session_id.
  - Results fetch: `queries.py:740–793` same check, emits `RESULTS_FETCH_FOREIGN_ROWS_REF` security event on mismatch, returns 403.
  - (Tool handlers themselves don't re-check session_id — they trust the agent context. The boundary is at the API layer.)
- **Session purge on end**: `result_cache.py:417–435` → `sessions.py:444`.

**`inspect_cached_result` operation coverage** (`cache_inspection_tools.py:120–422`):
- ✅ Supported: `filter` (8 operators), `top_n` (asc/desc), `describe` (full numeric summary), `group_summary` (sum/avg/count/min/max), `count_distinct`.
- ❌ Missing that analysts/LLMs plausibly ask for: **sort on multiple columns**, **distinct-on-multiple-columns**, **join two rows_refs**, **pivot / crosstab**, **percentile boundary filter** (e.g., "rows in p25..p75"), **correlation between two columns**, **string regex / case-insensitive contains**.

**Mission-threatening gaps**:

- **P1** **Zero observability on cache effectiveness**. No Prometheus metrics (`cache_hits_total` / `cache_misses_total`). The only hit-signal is an info log line in the export path (`queries.py:671–675`). A regression where the LLM stops routing follow-ups to cache tools (re-running SQL instead) is invisible until resource usage spikes. Fix: add cache hit/miss counters with operation labels; emit from `get_cached_rows` and `inspect_cached_result` handlers.
- **P1** **`get_cached_rows` silently caps limit to 50** (`cache_inspection_tools.py:38, 85–91`). Response includes `limit: 50` but the LLM's mental model may expect its requested limit. Fix: include `"requested_limit"` and `"actual_limit"` in response; LLM-side guidance to switch to `top_n` or `group_summary` for larger analytical operations.
- **P2** **Missing pivot/crosstab/correlate operations** force the LLM to re-run SQL for analyst-typical questions. Reduces cache value. Fix: add `pivot` and `correlate` operations; cap output to prevent context blow-up.

---

### E. Schema + data dictionary pipeline

**Files**: `backend/app/services/tools/{schema_tools.py, business_tools.py}`, `backend/app/services/sql_generation.py`, dictionary source in `backend/app/services/data_dictionary.py`.

- **`data_dictionary_context` origin**: built fresh per request at `chat.py:342–365` via `SQLGenerationService._get_data_dictionary_context()`. Semantic search (ChromaDB/Qdrant) on business terms + column descriptions → sanitized markdown blob (~500–3000 chars).
- **Freshness**: no context-level cache; rebuilt every request. Dictionary entries live in PostgreSQL, vector-indexed synchronously on `add_*` / `update_*` in `data_dictionary.py:394, 495, 1168, 1272`. Next agent call after update sees the change.
- **Tool availability without dictionary configured**: `lookup_business_term` is always bound. If no dictionary, returns helpful fallback ("might not be in the business dictionary yet…"). Agent still functions.
- **`search_tables`**: vector similarity (`schema_tools.py:41–123`), returns schema-qualified names (e.g. `demoapp.policies`). ✅ matches prompt requirement.
- **`get_table_schema` NoSQL coverage**: `schema_tools.py:240–243` emits `Partition Keys (REQUIRED in WHERE): ...` and `Clustering Keys: ...` for Cassandra when the parsed schema has those fields. DynamoDB parsed at `schema_tools.py:403–406` for sort keys. MongoDB has no explicit partition concept.

**Mission-threatening gaps**:

- **P0** **NoSQL partition-key info is conditional on vector-DB indexing quality**. `schema_tools.py:386–393` parses partition keys from the indexed schema — but there is no verification that the indexing process captured partition-key metadata in the first place. If indexing was incomplete, agent sees a schema without partition keys, generates queries that fail at execution time with "missing partition key" errors. Fix: add a consistency check in `get_table_schema()` for Cassandra/DynamoDB tables — if `partition_keys` is empty, re-query the live DB metadata and warn.
- **P1** **PII exposure via `get_sample_data`**. The `ColumnDescription` model has an `is_pii` boolean field (`data_dictionary.py:1094–1110`), but the sample-data tool does not consult it — actual sensitive values are returned unredacted. Fix: load column descriptions in the handler; mask columns flagged `is_pii=True` with `[REDACTED]`.
- **P2** **Stale schema in vector DB, no DDL invalidation**. When a DBA drops or adds a column upstream, the vector DB serves stale schema until manual reindex. The manual-refresh path exists (`distributed_lock.py:527–539`) but isn't auto-triggered. Fix: optional schema-change detector (metadata poll), or at minimum a warning when execution fails with "column doesn't exist" for a column that's in the indexed schema.

---

### F. Response assembly + frontend wire

**Files**: backend `app/api/chat.py`, `app/models/chat_models.py`, `app/services/answer_generator.py`; frontend `frontend/src/components/chat/AIResponseCard.vue`, `analyst/InsightCard.vue`, `analyst/FollowUpSuggestions.vue`.

- **ChatResponse ↔ frontend field map** (23 fields total, most wired correctly). Insights wiring held (commit 3a535cd): `chat.py:629` → `AIResponseCard.vue:375` → `InsightCard.vue:70–88` with defensive defaults (severity/title/description) at `InsightCard.vue:76–85`.
- **Chart pipeline**: 100% structured JSON end-to-end. No text-parsing dead weight. Chart assembled as dict at `chat.py:423–433` (pre-computed) or `chat.py:461–469` (LLM path), consumed directly by frontend chart component.
- **"See insights below" false promise** from commit ca1e691: verified absent from current `chat.py`, `react_agent.py`, `answer_generator.py`.
- **Error path**: `ErrorSanitizer.sanitize_error()` applied at `chat.py:392, 651`. No stack traces leak through this boundary. ✅
- **Stream events**: all emitted events are consumed in the frontend; `analyzing` is emitted but has no visual handler (non-critical; silent).

**Mission-threatening gaps**:

- **P0** **Empty-insights silent blank section**. When `execute_and_analyze` runs but detectors find no patterns AND LLM narrator is skipped (see C.P0), `insights=[]` is returned. `InsightCard.vue:80` v-if guard hides the component. User sees answer text + no insight cards, silently. Combined with C.P0, this is the most likely way a user experiences "talk to your data" as "mechanical stat dump".
- **P1** **5 waste fields produced-but-never-consumed**: `query_type`, `tool_calls_count`, `query_id`, `execution_time_ms`, `usage`. Plus `confidence` produced but only read conditionally. Wastes serialization; creates future consumer-producer drift risk. Fix: remove from `ChatResponse` OR start rendering (e.g., confidence as subtle indicator is a legitimate UX addition).
- **P1** **`key_findings` vs `insights` source duplication**. Both flow from the same `execution_result["insights"]` (`chat.py:417–421` and 629), but the code paths diverge cosmetically. A future refactor that changes one without the other creates a contradictory UI. Fix: derive `key_findings` from `insights` in a single place — or drop `key_findings` entirely if `insights` supersedes it.

---

### G. Prompt caching plan

**Files**: `backend/app/services/llm_service.py:428–475` (call site); `backend/app/services/react_agent.py:3069–3197` (prompt assembly).

- **Current state**: zero `cache_control` markers in backend. `llm_service.py:467` hardcodes `cached=False`.
- **Provider matrix**:
  - Anthropic: explicit `cache_control: {type: "ephemeral"}`, 5-min TTL, max 4 breakpoints, 90% discount.
  - OpenAI: implicit prefix caching for prompts >1024 tokens, 50% discount, no marker needed.
  - OAuth gateway: provider-dependent; gateway handler at `_call_oauth_gateway_with_tools` would need investigation.

**Prompt assembly order today** (inside `_build_contextual_system_prompt`):
1. `db_type_section` — prepended at line 3131 (this fragments the cache prefix; see risk below)
2. `SYSTEM_PROMPT` (lean 57-line)
3. `_aggregation_prompt_hint()` (conditional, often empty)
4. `data_dictionary_context` (stable per session)
5. Conversation history (grows per turn — do NOT include in cache segment)

**Optimal breakpoint**: right after `data_dictionary_context`, before conversation history. Everything above is stable per session; everything below varies per turn.

**Token math** (rough):
- Stable prefix: ~1,800–4,000 tokens typical (wider for large dictionaries).
- Cost reduction estimate for Anthropic: ~81% on prompt tokens (100K req/mo at ~2K prompt-tokens each: $600 → $114).
- TTFT: cached reads are faster; qualitative ~50–100ms gain.

**Recommended 3-phase rollout**:
1. **Observability first** — extend `LLMUsageData` with `cache_creation_input_tokens` and `cache_read_input_tokens`, read them from LiteLLM response, log cache hits. Ship without injecting cache markers (provider may already implicit-cache). Ungate Phase 2 on metrics appearing in logs.
2. **Feature-flagged dry-run** — add `ENABLE_PROMPT_CACHING` env var (default False). When on + model is Anthropic, inject `cache_control: {type: "ephemeral"}` on the system message. Canary 5–10% of prod. Gate next phase on ≥50% cache hits on turn 2+ with zero error-rate regression.
3. **GA** — flip flag to 100%. Optionally restructure prompt assembly so `db_type_section` is appended *after* `SYSTEM_PROMPT` (widens the stable-prefix cache region — reduces fragmentation from multi-DB tenants). Monitor for 2 weeks; gate success on ≥70% hit rate on repeat conversations.

**Small risks noted, all tractable**:
- `db_type_section` prepend fragments cache per db_type. Reorder is safe (pure static content).
- Deploy invalidates the cache (5-min TTL recovery, acceptable).
- Multi-tenant isolation is per-API-key on Anthropic side; already correct.

---

## Consolidated gap rollup — P0/P1/P2

### P0 — mission-critical; fix first

| # | Gap | Slice | Fix described |
|---|---|---|---|
| 1 | LLM narrator silently skipped when `llm_config` missing; returns stat-only insights with no signal to agent or UI | C | `query_tools.py:652–658` — add `narrator_status` and `insights_type` fields to response payload when narrator is bypassed |
| 2 | Empty insights array renders a silent blank section in UI (combines with #1 to produce the classic "mechanical stat dump" failure mode the mission exists to avoid) | F | `InsightCard.vue` — render an explicit fallback card when `insights=[]` AND we expected narration (distinguish from "no insights were needed") |
| 3 | `annotate_chart` tool description has no concrete "when to call" trigger — LLM skips it | B | `analysis_definitions.py:366–373` — prepend trigger scenarios |
| 4 | `question=` on `execute_and_analyze` is optional in schema — load-bearing behavior relies on prompt compliance alone | B/C | `tools/definitions.py:248` — change `required: ["sql"]` to `required: ["sql", "question"]` |
| 5 | NoSQL partition keys only returned when vector-DB indexing captured them — agent generates queries that fail at execution | E | `schema_tools.py:get_table_schema()` — for Cassandra/DynamoDB, verify `partition_keys` is populated; fall back to live metadata query if empty |

### P1 — significant operator blind spots; fix next

| # | Gap | Slice | Fix described |
|---|---|---|---|
| 6 | Raw exception strings leak into tool-result payload (DB errors, stack fragments) — LLM sees them, may emit despite SYSTEM_PROMPT voice rule | C | `query_tools.py:1306–1321` — route through `ErrorSanitizer.sanitize_error()` |
| 7 | Chart spec returns `None` without signal to frontend ("chart would help but failed" vs "not chartable") | C | Add `chart_possible: bool` + rationale field to response |
| 8 | Zero observability on cache hit rate — silent regression possible if LLM stops routing follow-ups to cache | D | Prometheus metrics `cache_hits_total` / `cache_misses_total` with operation labels, emitted from cache handlers |
| 9 | `get_cached_rows` silently caps limit to 50 — LLM's mental model may be off | D | Include `requested_limit` and `actual_limit` in response; nudge LLM toward `top_n`/`group_summary` |
| 10 | PII exposure via `get_sample_data` — `is_pii` flag exists but unused | E | Load column descriptions; mask `is_pii=True` columns |
| 11 | 5 waste fields in `ChatResponse` (`query_type`, `tool_calls_count`, `query_id`, `execution_time_ms`, `usage`) — drift risk | F | Drop or start rendering |
| 12 | `key_findings` vs `insights` duplicate source — future refactor could make them diverge | F | Derive `key_findings` from `insights` in one place or remove it |
| 13 | No per-iteration soft budget on the agent graph — slow query × 10 iter = 50 min worst case | A | Add wall-clock budget; subtract per-tool elapsed from remaining budget |

### P2 — nice-to-have; pick up opportunistically

| # | Gap | Slice | Fix described |
|---|---|---|---|
| 14 | `question=` missing has no log/signal when handler falls back to generic prompt | C | Log INFO when blank; optionally surface `question_available` in response |
| 15 | Sampling disclaimers pollute the `insights` list | C | Move to `sampling_used: {...}` top-level field; keep insights pure |
| 16 | `inspect_cached_result` missing pivot / crosstab / correlate / regex-match / multi-column ops | D | Add operations as capacity allows |
| 17 | Stale schema in vector DB — no auto-invalidation on DDL | E | Optional schema-change detector; at minimum warn on "column doesn't exist" when that column is in the indexed schema |
| 18 | `consecutive_no_tools` is a "ghost" routing signal (locally read, never consulted by global router) | A | Either wire into `should_continue()` or remove from state schema |
| 19 | `_CRITICAL_STATE_FIELDS` tuple is manually maintained — drift risk for future state fields | A | Derive from state class reflection, or add a test that asserts every routing field appears in the tuple |
| 20 | `annotate_chart`-chain discovery depends entirely on tool descriptions (post-prompt-diet) | B | Monitor; if LLM skips the chain in production, add one sentence back to SYSTEM_PROMPT |

---

## Recommended next steps

### Ready to fix now (low-risk, high-value)

- P0 #4 (`question=` required) — single-line schema change, eliminates a systemic reliance on prompt compliance
- P0 #3 (`annotate_chart` description) — prose edit, no behavior change needed
- P1 #6 (error sanitization on `execute_and_analyze` failure paths) — uses existing `ErrorSanitizer`, no new infrastructure
- P1 #11 (drop waste fields) — subtractive change, reduces surface area
- P1 #12 (unify `key_findings` derivation) — removes fragility

### Needs design discussion before implementation

- P0 #1 + #2 together (narrator-skipped signal + empty-insights fallback UI) — this is the "talk to your data" mission-critical pair. Worth a brief spec on what the user should see in each of the three degraded cases: (a) narrator skipped, (b) narrator ran but found nothing, (c) narrator errored.
- P0 #5 (NoSQL partition-key verification) — may need a live DB metadata path that doesn't exist today; scope out before committing.
- P1 #8 (cache observability) — pick metrics stack (Prometheus vs OpenTelemetry vs logs-only) to align with whatever's already in use.

### Deferred intentionally

- G (prompt caching plan) — the plan is ready; Phase 1 (observability) is safe to start any time. Phases 2 and 3 depend on Phase 1 data.
- P2 items — opportunistic; no mission impact.

### Not in scope (already deferred)

- BigQuery / Snowflake async executors (3b.3, 3b.4)
- M5 / M7 long-standing edge cases
- Multi-tenancy beyond current rows_ref IDOR

---

## Appendix — raw-agent references

This doc synthesizes 7 parallel Explore-agent reports. For deeper evidence on any specific finding, the agents traced the following files and line ranges:

- **A (graph)**: `react_agent.py:237–282, 1337–2162, 2790–2980, 3199–3805`
- **B (tools)**: `tools/definitions.py` (18 tools), `tools/analysis_definitions.py`, `react_agent.py:289–635`
- **C (analyze)**: `tools/query_tools.py:730–1321`, `enhance_insights_with_llm` at 579–727
- **D (cache)**: `result_cache.py:49–435`, `tools/cache_inspection_tools.py:38–422`, `api/queries.py:630–793`
- **E (schema/dict)**: `tools/schema_tools.py:41–450`, `tools/business_tools.py:15–85`, `services/data_dictionary.py`, `services/sql_generation.py`
- **F (response)**: `api/chat.py:342–1086`, `models/chat_models.py:88–216`, `frontend/src/components/chat/AIResponseCard.vue`, `analyst/InsightCard.vue`, `analyst/FollowUpSuggestions.vue`
- **G (caching)**: `llm_service.py:428–475`, `react_agent.py:3069–3197`
