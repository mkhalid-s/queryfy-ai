# Deep Audit — 2026-05-09

**Scope**: 9-perspective audit of QueryfyAI on `main` (head `e038523`) plus the unmerged `redesign/split-pane-spike` branch (28 commits, +6.2k LOC), plus a strategic-positioning check against the mid-2026 NL2SQL landscape.

**Method**: 9 parallel evidence-gathering agents, each with a non-overlapping scope. Six included web research. All findings are file:line- or URL-cited in the per-agent reports archived under `.reviews/2026-05-09/`. This doc is a synthesis, not a proposal — actions are *described*, not committed to.

---

## Executive verdict

**The codebase is competent, secure, well-tested, and over-engineered around a 2024 mental model of what NL-to-data should be in mid-2026.** The world moved to (a) artifact-first agentic workspaces, (b) MCP-server-as-the-integration-shape, and (c) semantic-layer-first answer routing. QueryfyAI sits in the shrinking middle: better than the median open-source competitor on production ops and security, but visibly behind the 2026 frontier on product surface, retrieval rigour, and integration shape.

The headline competitor it has been benchmarking against — **Vanna AI** — was **archived on 2026-03-29**. WrenAI repositioned in 2026 from "NL2SQL tool" to "open context layer for AI agents." The category QueryfyAI was building against has effectively dissolved.

The good news: the project's recent strategic moves (the parked PydanticAI migration, the unfinished split-pane redesign, the analyst-mode wave fixes, the OAuth-gateway path) are all directionally correct. The pattern is **finishing already-started work, not restarting**.

| Slice | Verdict | Top risk |
|---|---|---|
| A — Backend architecture | HEALTHY | `react_agent.py` at 4,190 LOC is a comprehension cliff |
| B — Competitive landscape | BEHIND on product shape | Vanna archived; market moved to MCP + semantic-layer; QueryfyAI not in either category |
| C — RAG / schema SOTA | 4 P0s | Single-stage dense retrieval; `get_column_context()` ignores the query; ada-002 / MiniLM in 2026 |
| D — Frontend / UX | NEEDS WORK on main; spike closes gap | Kitchen-sink chat bubble; spike has 5 still-missing 2026 patterns |
| E — DevOps / supply-chain | OK trending STRONG | `release.yml` Trivy still on `@master`; no SBOM/cosign |
| F — Reliability / observability | OK with one P0 open | 8 tool handlers + registry catch-all still leak `str(e)`; `active_sessions` gauge never updated |
| G — Strategic critic | BEHIND | Audit-driven not delivery-driven; calcifying parked decisions |
| H — QueryfyAI KB utilization | One adopt + one explore | Enterprise Gateway as LiteLLM provider; MCP server for Platform Agents |
| I — Agent framework deep dive | Stick (with extraction first) | Burr is the foundation-governed dark horse; Volcano is TS-only — skip |

---

## Recurring themes across reviewers (highest-signal)

### 1. Finish what you started — five projects mid-air

Multiple reviewers independently surfaced the same anti-pattern: substantial work was begun, then *parked* before completion. The leverage move in every case is to *complete* it, not start something new.

| Started | Status | Reviewer | Cost to finish |
|---|---|---|---|
| Split-pane UI redesign (28 commits, +6.2k LOC on `redesign/split-pane-spike`) | Spike branch, not on main | D, G | ~1 week to close 3 gaps + merge |
| LangGraph → PydanticAI extraction | Doc parked 2026-04-16, no code | A, G, I | A's "extract first" path: ~5 days; full rebuild: 4-6 weeks |
| `release.yml` Trivy / third-party action SHA-pinning | CI is pinned (PR #59); release isn't | E | ~30 min — same SHAs |
| Audit-doc P1 #6 (error sanitization) | Only `execute_and_analyze` was sanitized; 8 other handlers + registry catch-all still leak | F | ~50 LOC across 9 files |
| Audit-doc P1 #8 (cache hit/miss observability) | Logged, not metric'd | E, F | Single counter + Grafana panel |

### 2. MCP-server interface — the highest-leverage *strategic* move

**Two independent reviewers (B, H) and one supporting reviewer (I) converged on the same recommendation**: expose QueryfyAI's existing tools (`search_tables`, `get_table_schema`, `execute_and_analyze`, `inspect_cached_result`, `lookup_business_term`) as an MCP server alongside the current REST/SSE API.

Why it's the highest-leverage move:
- The `ToolRegistry` already has MCP spec converters (`tools/registry.py`). The transport is the only missing piece.
- Reframes QueryfyAI from "another NL2SQL UI" to "the governed-DB MCP server with NoSQL + OAuth-gateway support" — a category that *isn't* dissolving.
- Makes QueryfyAI consumable by Claude / ChatGPT / Cursor / Windsurf / Vercel AI SDK / OpenAI Agents SDK / External Platform Agents — i.e., the 78% of enterprise AI teams already on MCP per Q1 2026 surveys.
- Hedges every framework decision — works whether the agent stays on LangGraph, moves to Burr/PydanticAI, or gets consumed by an external orchestrator.

### 3. The retrieval layer is the deepest technical gap

Reviewer C identified four P0s in the schema-understanding pipeline. The most surprising:

- **`data_dictionary.get_column_context()` ignores its `query` parameter** (`data_dictionary.py:1374-1404`) — it returns *every* active `ColumnDescription` for the connection regardless of what the user asked. This is non-semantic context dumping; it's not retrieval at all.
- **Single-stage dense retrieval**, no BM25, no reranker. Causes the abbreviated-column-name failure mode that Spider 2.0 demolishes (`cust_id` ↔ "customer id").
- **Embedding model is `text-embedding-ada-002` (deprecated by OpenAI in 2024) or `all-MiniLM-L6-v2` (2021)** (`vector_db.py:19-52`).
- **Table-level chunks only** — column-level embeddings with cell-value snippets are 2026 best practice (CHESS pattern); QueryfyAI commits the schema as a comma-joined string in a single per-table doc.

The fix path is well-trodden in the literature (CHESS, MAC-SQL, RESDSQL, "Rethinking Schema Linking" arXiv:2510.14296) and incremental — add BM25 alongside dense, fuse via RRF, rerank with `bge-reranker-v2-m3`, fix `get_column_context()` to actually take a query. None of it is research-grade work.

### 4. The product surface is the strategic gap

Reviewers D and G independently described the same anti-pattern: the analyst turn on `main` (`AIResponseCard.vue:1-365`) stacks answer + key findings + sampling banner + insights cards + ContentTabs (SQL/Data/Chart) + follow-up suggestions + collapsible agent timeline + footer inside one tall chat bubble. This is the **canonical 2024 anti-pattern** that every modern competitor (Hex, WrenAI, Cortex Analyst, Spotter, Claude Artifacts, ChatGPT Canvas) explicitly retired in 2024–2025.

The `redesign/split-pane-spike` branch implements the modern pattern almost line-for-line from `docs/ui-redesign-research-2026-04-28.md`. **Shipping the spike is the single highest-leverage UX move available.** The spike is not the destination — it still misses 5 2026 patterns (typed tool-call cards, editable SQL with re-run, pin/share artifact, @-mention table/column in `QueryBar.vue`, streaming markdown answers) — but it closes the gap with its competitors.

### 5. "Finish, then evaluate" beats "rebuild" on framework choice

Three reviewers (A, G, I) addressed the LangGraph migration question and converged with one important amendment to the parked 2026-04-16 review:

- **A**: extract `agent/policy.py` + `agent/message_validation.py` + `agent/streaming.py` from `react_agent.py` *first*. Provably equivalent (pure-function moves), framework-independent, makes the eventual swap a routine refactor instead of a strategic bet. Re-scopes the migration target from "PydanticAI specifically" to "raw LiteLLM loop + custom policy" because the current code is *already* a custom policy trapped inside a graph wrapper.
- **G**: agreed on the rebuild necessity but framed it as the Carmack cut — most of the structural bugs (`architecture-audit-2026-04-16.md`) evaporate in a clean rewrite because they're emergent properties of the LangGraph `Annotated[..., operator.add]` state model and the JSON-string-via-ToolMessage contract.
- **I**: agreed with A's sequencing. Added a dark-horse alternative: **Apache Burr** (Apache-incubating-governed, Python, LangGraph-shaped). When you reach the evaluate step, spike Burr alongside PydanticAI — Apache governance materially de-risks the vendor-pivot scenario that already burned the AutoGen → Microsoft Agent Framework crowd.

**Volcano (Kong) is TS-only — disqualifying.** Don't switch to it.

### 6. Audit-driven development without delivery-driven development

Reviewer G's sharpest observation, supported by Reviewer F's data:

- 5 audit docs since January 2026, each with P0/P1/P2 lists.
- Commit `a74caea` claims "all waves — reliability, observability, security, schema refresh, PII redaction" addressed.
- F verified: only *some* P0/P1 items are actually closed. Concretely: P1 #6 (sanitization) is partial; P1 #8 (cache hit/miss observability) is open; `active_sessions` gauge is defined but never updated; OTEL is largely cosmetic (4 manual spans, named helpers `trace_llm_call`/`trace_db_query`/`trace_agent_step` never called); ~33 integration tests skipped with "uses obsolete architecture."

The audits are high quality. The shipping-against-them is partial. The reading-to-shipping ratio is wrong.

---

## Consolidated P0/P1 rollup

> **Status as of Tier A + Tier A.5 (2026-05-12):** P0 #1, P0 #4, P0 #5, P1 #9, P1 #10, P1 #17 are CLOSED on `plan/audit-2026-05-rollout`. P0 #2 / P0 #3 / P0 #6 + P1 #7 / P1 #8 / P1 #18 are scheduled for Tier B (retrieval); P1 #15 for Tier C (react_agent.py extraction). The "Status" column below tracks closure; the original audit text is preserved verbatim above the row for historical fidelity.

### P0 — fix first

| # | Gap | Slice | Concrete fix | Cost | Status |
|---|---|---|---|---|---|
| 1 | 8 tool handlers + `tools/registry.py:303` catch-all return raw `str(e)` to LLM (and SSE error path at `chat.py:844` to browser) | F | Sanitize at the registry boundary; sweep 8 handlers (~50 LOC) | ~half-day | **CLOSED** — A4 commit `e2ca2ed`; F8 regression test at `backend/tests/smoke/test_f8_credential_leak_regression.py`; F9 extensions (AWS/JWT/`ghp_`/Bearer/Slack/GitLab) closed in Tier A.5. |
| 2 | `data_dictionary.get_column_context()` ignores `query` parameter; returns all column descriptions | C | Embed query, retrieve top-K, drop "return all" path | 1 day | OPEN — Tier B2, gated on A7 harness measurement floor. |
| 3 | Single-stage dense retrieval, no BM25, no reranker | C | Add BM25 + RRF + `bge-reranker-v2-m3` rerank in `vector_db.get_relevant_schema()` | ~3 days | OPEN — Tier B1, gated on A7. |
| 4 | `release.yml:212,220` Trivy unpinned (`@master`); `dorny/test-reporter`, `codecov`, `softprops/action-gh-release` also unpinned | E | Same SHA pin pattern as PR #59 | ~30 min | **CLOSED** — A1 commit `c4d62db`. (First-party `actions/*` and `docker/*` remain at symbolic majors; flagged by the 2026-05-11 12-perspective security reviewer as scope-incomplete; deferred to its own focused PR.) |
| 5 | No SBOM, no cosign, no provenance attestation on Docker images | E | `docker/build-push-action` natively supports `sbom: true` + `provenance: mode=max`; cosign keyless via GitHub OIDC | ~2 days | **CLOSED** — A2 commit `2d5fec6`. (F1 verify-in-`deploy-trigger.yml` is the follow-up enforcement gate, still open.) |
| 6 | `redesign/split-pane-spike` not merged — main UI is the canonical 2024 anti-pattern | D, G | Close 3 gaps (drop 12-particle empty-state hero; sticky follow-up chip strip; editable SQL with re-run) and ship | ~1 week | OPEN — Tier C4 (Phase 1 redo, task #53). |

### P1 — significant; fix next

| # | Gap | Slice | Fix described | Status |
|---|---|---|---|---|
| 7 | Embedding model is `ada-002` (deprecated) or `MiniLM-L6-v2` (2021) | C | Switch to `text-embedding-3-large` or `bge-m3` | OPEN — Tier B3. |
| 8 | Table-level chunks only; no column-level embeddings or cell-value snippets | C | Add `column_embeddings` collection with `(table, column, type, description, top-K distinct values)` chunks; bidirectional retrieval per arXiv:2510.14296 | OPEN — Tier B4. |
| 9 | `active_sessions` Prometheus gauge defined but never updated anywhere | F | Wire from `session_store` lifecycle | **CLOSED** — A5 commit `bea3d15`. F20 (MultiProcessCollector wiring under N-worker gunicorn) is the still-open follow-up. |
| 10 | Result cache hit/miss has zero Prometheus instrumentation | E, F | `queryfyai_result_cache_operations_total{operation, result}` counter + Grafana panel | **CLOSED** — A6 commit `a4e35a0`. |
| 11 | No LLM cost cap — `LLMMetricsTracker` accumulates spend but no code enforces ceiling | F | Add `MAX_COST_PER_SESSION`, `MAX_TOKENS_PER_DAY` settings; check in `llm_service.py` before call | OPEN — out of Tier A scope. |
| 12 | OTEL is largely cosmetic — 4 manual spans, named helpers never called | F | Wire `trace_llm_call`/`trace_db_query`/`trace_agent_step` at the agent-step boundary, or delete the helpers | OPEN. |
| 13 | Mixed logging: 45 modules use stdlib `logging`, 23 use structlog; 365 f-string log calls | F | Migrate stdlib calls to structlog; structured fields are lost today | OPEN. |
| 14 | ~33 integration tests skipped with "uses obsolete architecture" | F | Either rewrite against current architecture or delete with explicit decision log | OPEN. |
| 15 | `react_agent.py` at 4,190 LOC — comprehension cliff | A | Extract `agent/policy.py` (~600), `agent/message_validation.py` (~300), `agent/streaming.py` (~700) — provably equivalent moves | OPEN — Tier C1. |
| 16 | Wheelhouse pinned-to-floor (`>=`), not lock-hashed | E | `uv pip compile --generate-hashes` → `requirements.lock`; install with `--require-hashes` | OPEN. |
| 17 | No top-level `permissions: contents: read` on workflows | E | Add to `ci.yml`, `release.yml`, `benchmark*.yml`, `deploy-trigger.yml` | **CLOSED** — A3 commit `dddb58b`; `gh-pages.yml` follow-up (F39) closed in Tier A.5. |
| 18 | Schema staleness: no DDL detection, no auto-reindex on "column not found" | C | Hook `error_classifier.py` "column does not exist" → enqueue `schema_refresh.refresh_table_schema()` | OPEN — partially addressed by wave 2b `schema_refresh.py`; auto-reindex hook still needed. |

---

## What's notably good

Resist the temptation to read the criticism as "this project is broken." Most reviewers explicitly cited strengths.

- **Wave-2 reliability fixes are real**, not just claimed: wall-clock budget (`react_agent.py:2924-2941`), two-counter circuit breaker (`react_agent.py:3009-3025`), pool pre-flight + discard-and-retry (`connection_pool_manager.py:718-738`), shutdown drain (`core/shutdown_drain.py`), HMAC IDOR guard (`api/queries.py:630-656`), Wave 2C SQL-aware PII narrowing (`query_tools.py:265-339`).
- **K8s manifests are production-grade**: PDB (`minAvailable: 2`), HPA, NetworkPolicy, `runAsNonRoot`, `readOnlyRootFilesystem`, dropped capabilities, seccomp `RuntimeDefault`, topology-spread, pod anti-affinity, ephemeral-storage limits, separate ServiceAccount with `automountServiceAccountToken: false`. Most teams ship without half of these.
- **PR #59's Trivy pin pattern is exemplary** — cited by Reviewer E as a model. The inline comment explaining tag-vs-digest is rare and valuable.
- **`docker-compose.production.yml` security posture**: `no-new-privileges`, resource limits, log rotation, fail-fast on missing secrets, Traefik rate-limit + security headers.
- **Prometheus + structlog + OpenTelemetry are actually wired** in `app/main.py` and `app/api/metrics.py` — not just declared in `requirements.txt`. (The OTEL spans being thin is a separate finding, but the plumbing is real.)
- **Spike branch quality**: `WorkspaceSplit.vue` (343 LOC, drag handle with rAF throttling, keyboard a11y, persisted width, container queries), `ArtifactPane.vue` (`v-show`-mounted ECharts to avoid re-init), keyboard-resizable separator with proper `role="separator"` ARIA — better a11y than most competitors.
- **The 5 structural bugs from `architecture-audit-2026-04-16.md` are all closed** (Reviewer A verified, file:line evidence).
- **Wave 2C PII SQL-narrowing closes the OR-semantics false-positive workaround documented in `backend/CLAUDE.md`** — a non-trivial audit-doc gap that *is* genuinely shipped.

---

## Strategic call

**Refactor + product-surface pivot, in that order.** Not "Hold" — that's what the project has been doing for 6 weeks and the result is calcification (Reviewer G). Not "Pivot to a different product" — there's real value here (multi-DB executors, security hardening, OAuth gateway, the benchmark harness) that should not be thrown away.

Sequence:

1. **Refactor the engine** — Reviewer A's extraction (`agent/policy.py` + `message_validation.py` + `streaming.py`) is the prerequisite for any framework swap and is provably equivalent. Do not commit to PydanticAI yet — when the extraction lands, spike Burr alongside PydanticAI for 2 days before deciding.
2. **Pivot the surface** — finish the split-pane spike, close the 3 gaps Reviewer D named, ship as the only UI. Drop the 2022-era empty-state hero.
3. **Sharpen the positioning** — pick one: (a) the secure-NL2SQL-for-enterprise-OAuth-gateways niche; (b) an MCP server first, with the current UI as a consumer; (c) turn the benchmark harness (`0fd5540`) into a public leaderboard. Reviewer G called the benchmark harness the most strategically interesting commit of the year that got zero follow-up — option (c) is meaningfully differentiating in mid-2026.

---

## Fact-check on the findings (2026-05-09 evening)

Owner pushed back on the original plan as feeling regressive. A second pass verified each load-bearing claim against the actual codebase. Some held up; some did not.

### Internal claims — verified ✓

| Claim | Evidence | Status |
|---|---|---|
| `react_agent.py` is 4,190 LOC | `wc -l` = 4,190 | ✓ |
| `redesign/split-pane-spike` = 28 commits, +6,231/−430 LOC across 27 files | `git rev-list --count` and `git diff --shortstat main...origin/redesign/split-pane-spike` | ✓ |
| `data_dictionary.get_column_context()` ignores its `query` argument | `data_dictionary.py:1374-1404` — first param `query: str` is **never referenced** in the function body | ✓ confirmed in source |
| Embedding model is `text-embedding-ada-002` or `all-MiniLM-L6-v2` | `vector_db.py:37,39,143,145` | ✓ |
| `tools/registry.py` catch-all returns raw `str(e)` | `tools/registry.py:301-305` returns `f"Error: {error_msg}"` where `error_msg = f"Error executing {name}: {str(e)}"` | ✓ |
| Multiple tool handler files leak `str(e)` | 26 grep hits across `backend/app/services/tools/*.py` (Reviewer F said "8 handlers"; the count is higher because some files have multiple sites) | ✓ directionally; figure adjusted |
| `release.yml:212,220` Trivy on `@master` (not pinned) | grep confirms both lines | ✓ |
| `dorny/test-reporter@v1`, `codecov/codecov-action@v5`, `softprops/action-gh-release@v2` not SHA-pinned | grep confirms | ✓ |
| 45 modules use stdlib `logging.getLogger`, 22 use `get_logger`/`structlog` (Reviewer F said 23) | grep counts | ✓ (within ±1) |
| 419 f-string log calls in `backend/app` (Reviewer F said 365) | grep counts | ✓ directionally; under-counted in the original report |
| 33 integration tests skipped (cancellation 5 + db_resilience 8 + agent_workflows 10 + llm_resilience 10) | grep counts | ✓ exact |
| 4 manual OTEL spans in `backend/app` | grep counts | ✓ exact |
| Empty-state hero in `ChatContainer.vue` has floating particles, pulse ring, tagline rotation | lines 11, 16, 20, 45, 48-53, 213-225, 280-292 | ✓ |
| Wave-2 reliability fixes are real (wall-clock budget, FIX flags, distributed-lock fail-loud, SQL-aware PII narrowing, shutdown drain) | spot-checked at `react_agent.py:2924-2941`, `core/config.py:141`, `distributed_lock.py:154-178`, `query_tools.py:265`, `core/shutdown_drain.py` exists | ✓ |
| PR #59 Trivy pin pattern landed on `ci.yml` main | `aquasecurity/trivy-action@ed142fd0... # v0.36.0` present at both call sites | ✓ |
| `active_sessions` Prometheus gauge defined but never updated | `metrics.py:134, 367` define it; `update_active_sessions(count)` is **not called from anywhere** in `backend/app` | ✓ |
| `AIResponseCard.vue` is a stacked turn | File is 1,304 LOC (Reviewer D's "1-365" was citing the script-setup range, not file size). Stacked-turn IA is real but the LOC framing was misleading. | ⚠️ partial — IA confirmed; LOC ref clarified |

### Internal claims — refuted or hollow ✗

| Original recommendation | What verification showed | Status |
|---|---|---|
| "Delete the `_future/` directory" (Reviewer G) | `_future/` does **not exist as source**. Only as `.mypy_cache/3.13/app/services/_future/*.json` cache artifacts. There is nothing to delete. | ✗ hollow |
| "Delete the 'future direction' half of `ROADMAP.md`" (Reviewer G) | The "Future Direction" section is the project's stated strategic plan: Adaptive Intelligence (mode unification), Enterprise Governance (RLS, multi-tenant), Scaling Architecture (3-tier), Learning Loop. Deleting it would erase direction, not declutter. | ✗ rejected |
| "Delete the 5 (8) analysis engines" (Reviewer G) | `backend/app/services/analysis_engines/` is **actively imported** by `tools/query_tools.py`, `tools/analysis_tools.py`, and across `analysis_engines/{insight_detector,comparisons,statistics}.py`. Deletion without replacement would break the live tool layer. | ✗ rejected |
| "Delete the analyst/standard mode split entirely in 14 days" (Reviewer G) | Mode split is wired into `App.vue:802,989,1112`, `api.js:234` (different timeouts!), and tests. The ROADMAP already proposes the right answer: **Adaptive Intelligence** with intent-based routing. That's the unification path; deletion in 14 days isn't. | ✗ rejected |
| "Fix `get_column_context()` in 1 day" | Called from `sql_generation.py:193` (hot path, every SQL generation). Switching from "return all" to top-K is a semantic behaviour change — callers may lose access to columns they currently see. Needs flag-gated rollout with measurement, not a same-day fix. | ⚠️ correct as a finding, wrong as an estimate |
| "Merge spike in ~1 week" | 6.2k LOC across 28 commits. Closing 3 gaps + integration testing + bake time more realistically = 2-3 weeks. | ⚠️ optimistic |

### External / strategic claims — flagged as "per reviewer, not re-verified"

These are taken on trust from the reviewer reports' citations and were not re-verified in this fact-check pass. They affect strategic conclusions, not load-bearing code claims:

- Vanna AI archived 2026-03-29 (Reviewer B, cited GitHub URL)
- WrenAI repositioned to "open context layer" 2026-05-07 (Reviewer B)
- Volcano (Kong) is TS-only (Reviewer I, cited Kong blog)
- Apache Burr is Apache-incubating-governed (Reviewer I)
- 78% of enterprise AI teams on MCP per Q1 2026 surveys (Reviewer B, cited DigitalApplied)
- AI SDK 5 has Vue/Nuxt support (Reviewer D, cited ai-sdk.dev)
- All academic-paper references (CHESS, MAC-SQL, RESDSQL, "Rethinking Schema Linking" arXiv:2510.14296) — Reviewer C cited URLs but the algorithmic claims weren't tested against this code.

---

## Plan — risk-tiered

The original 90-day plan was too aggressive on sequencing and folded in at least four refuted recommendations. This rewrite separates the work by **regression risk**, so the owner can pick a comfort level rather than commit to a calendar.

### Tier A — Pure additive, near-zero regression risk

Each item is independently mergeable as a small PR. Nothing in this tier changes existing behaviour for users; everything either adds observability, hardens build/release, or introduces new functionality alongside (not instead of) the current code path.

| Item | Source | Estimate |
|---|---|---|
| Pin `release.yml` Trivy + `dorny/test-reporter`, `codecov/codecov-action`, `softprops/action-gh-release` to commit SHAs | E P0 #4 | ~30 min |
| Add SBOM (`sbom: true`) + provenance (`provenance: mode=max`) + cosign keyless signing to `docker/build-push-action` | E P0 #5 | ~2 days |
| Add top-level `permissions: contents: read` defense-in-depth on all workflows | E P1 #17 | ~1 hour |
| Sanitize tool errors at the ToolRegistry boundary (`tools/registry.py:301-305`) — change `f"Error: {error_msg}"` to use `ErrorSanitizer.sanitize_error(e)` | F P0 #1 | ~half-day |
| Wire `update_active_sessions(count)` from `session_store` lifecycle | F P1 #9 | ~1 day |
| Add `queryfyai_result_cache_operations_total{operation, result}` Prometheus counter + Grafana panel | E + F P1 #10 | ~1 day |
| Build a `recall@k` retrieval-quality harness as a standalone offline script (read-only; cannot break production) | C move 3 | ~2 days |
| Ship an **MCP server interface** alongside the existing REST/SSE API, exposing existing tools (`search_tables`, `get_table_schema`, `execute_and_analyze`, `inspect_cached_result`, `lookup_business_term`) | B move 1 + H move 3 + I | ~1-2 weeks |
| Add typed tool-call cards in the frontend (Vercel AI Elements pattern, ported to Vue) | D move B | ~3-5 days |

**This tier alone closes the security-sensitive gaps, the highest-leverage strategic move (MCP), and the highest-leverage observability gaps. None of it requires deleting or behaviourally changing anything that currently works.**

### Tier B — Behaviour change with well-understood blast radius (flag-gate + measure)

Each item is a real behaviour change. None should ship without an off-by-default flag and a before/after measurement on the recall@k harness or production telemetry.

| Item | Why it's risky | Mitigation |
|---|---|---|
| Add hybrid retrieval (BM25 + RRF + cross-encoder rerank) in `vector_db.get_relevant_schema()` | Different tables retrieved → could regress queries that currently work via dense-only | Build harness first (Tier A); add `RETRIEVAL_MODE=dense\|hybrid` setting; run both for a week; flip default only if recall@k improves with no degradation |
| Fix `get_column_context()` to use its `query` argument | Today returns *all* column descriptions; switching to top-K may lose columns the LLM currently sees | Flag `COLUMN_CONTEXT_MODE=all\|topk`; default `all`; canary on dev; measure before flip |
| Switch embedding model from `ada-002` / `MiniLM-L6-v2` to `text-embedding-3-large` or `bge-m3` | Full reindex required; recall profile changes | Stage as parallel collection; A/B retrieval; swap after measurement |
| Add column-level embeddings collection with cell-value snippets (CHESS pattern) | Additive in storage; combined with bidirectional retrieval changes ranking | Build alongside table-level; combine via RRF; flag |
| Adopt Enterprise Gateway as a LiteLLM custom-endpoint provider | New auth path; mid-conversation 401 if budget exhausts | Feature flag, default off; mirror existing OAuth-gateway template; surface `x-budget-remaining` |
| LLM cost cap (`MAX_COST_PER_SESSION`, `MAX_TOKENS_PER_DAY`) | Could prematurely terminate legitimate sessions | Default to permissive; tighten with telemetry |
| Wire `error_classifier.py` "column does not exist" → enqueue `schema_refresh.refresh_table_schema()` | Could thrash the schema index under repeated bad queries | Rate-limit per (connection, table); structured-log first, action second |
| Migrate ~365–419 stdlib `logger.info(f"...")` calls to structlog | Format change in JSON logs; downstream consumers may parse on string shape | Sweep one module at a time; keep stdlib `logging.getLogger` aliased; verify log analytics still parse |

### Tier C — Larger refactors that need explicit owner decision + bake time

These are real moves but each has natural pacing. None of them should be on a 14-day clock.

| Item | Real timeline | Notes |
|---|---|---|
| Extract `agent/policy.py` + `agent/message_validation.py` + `agent/streaming.py` from `react_agent.py` | 2-3 weeks if cautious | "Provably equivalent" only with extreme care: 16 `FIX_*` flag branches, 60+ TypedDict fields. One module at a time; full test pass between each; no behaviour changes mixed in. |
| Merge `redesign/split-pane-spike` to main | 2-3 weeks of work, then ~2 weeks bake | Land **with both UIs available behind `UI_LAYOUT=classic\|split` flag** for ~2 weeks before deleting the old `AIResponseCard.vue` rendering path. Don't merge-and-delete in one PR. |
| Implement Adaptive Intelligence (the ROADMAP's mode-unification path) | Multi-week | Already in ROADMAP. Don't conflate this with "delete the standard mode" — the unification *is* the right move; the deletion-first framing isn't. |
| Spike Apache Burr alongside PydanticAI when the policy.py extraction is stable | 2-day spike + decision | Do this **after** extraction lands, not before. The extraction makes the framework choice a routine refactor. |

### Tier D — Recommendations to ignore

These came from Reviewer G and were retracted after fact-check verification. They're listed here so the doc has an audit trail — not to be acted on.

| Original | Why ignore |
|---|---|
| ~~Delete `_future/` directory~~ | Doesn't exist as source. Only mypy cache artifacts. |
| ~~Delete the "future direction" half of `ROADMAP.md`~~ | That section *is* the strategic plan. Deletion would erase direction. |
| ~~Delete the 8 analysis engines~~ | They are actively imported by `tools/query_tools.py` and `tools/analysis_tools.py`. The "modern LLMs do this natively" claim is an empirical hypothesis that requires A/B evaluation before any deletion is even considered. |
| ~~Delete the analyst/standard mode split in 14 days~~ | Wired into `App.vue:802,989,1112`, `api.js:234` (different timeouts), tests. The ROADMAP already has the right unification path (Adaptive Intelligence). |

### What this means in practice

**You don't need a 90-day calendar.** You need a comfort tier and a checklist.

- **Conservative path**: ship every Tier A item over the next 6-8 weeks as small PRs. Each one is independently revertible. At the end, the project has closed every security-sensitive finding, has the highest-leverage strategic move (MCP server) shipped, and has a measurement harness for everything in Tier B. Nothing has regressed.
- **Moderate path**: Tier A in parallel with one Tier B item at a time, behind flags, with measurement. Pick the Tier B item with the strongest evidence of upside (probably hybrid retrieval, since Reviewer C's evidence was the strongest).
- **Ambitious path**: Tier A → Tier B → Tier C in sequence. Pace gated by tests passing and telemetry, not calendar. The spike merge alone could be a quarter of work if you want it done right.

**Skip Tier D entirely.** The fact-check found these recommendations don't survive contact with the actual code.

---

## Decisions deferred — owner input needed

The synthesis stops short of committing to:

1. **Vue or React** — Reviewer D says **stay on Vue** (Vercel AI SDK 5 has Vue/Nuxt support; spike is mature; alternate UI framework migration already parked). Filed as decided unless the owner re-opens.
2. **Framework target** when the extraction completes — PydanticAI vs Apache Burr vs raw-LiteLLM-loop. Decide via 2-day spike, not paper review.
3. **One-of-three product positioning** for the day-76-90 slot. Owner call.
4. **Whether to ship the Enterprise Gateway adoption as opt-in or default-when-flag-set** — depends on whether the deployment is enterprise-internal or OSS-first.

---

## Where the per-reviewer reports came from

The full per-reviewer reports (each ~1,200–1,500 words with file:line and URL citations) were generated by 9 background agents on 2026-05-09 with these scopes:

- **A**: Backend architecture & agent loop reality check
- **B**: NL2SQL competitive landscape & strategic positioning (Vanna, WrenAI, DataHerald, LangChain, LlamaIndex, Hex/Mode/Julius, BIRD/Spider 2.0)
- **C**: RAG & schema-understanding SOTA (CHESS, MAC-SQL, DAIL-SQL, RESDSQL, hybrid retrieval, BIRD-bench)
- **D**: Frontend & UX modernization (Hex Notebook Agent, WrenAI, Cortex Analyst, Vercel AI Elements, AI SDK 5)
- **E**: DevOps / CI/CD / supply-chain / infra (SLSA, sigstore, GitHub hardening guide)
- **F**: Reliability, error handling, observability (sanitization, OTEL, Prometheus, integration tests)
- **G**: Strategic critic / honest verdict (Linus / Carmack / delete-not-improve cuts, 90-day plan)
- **H**: Enterprise LLM KB utilization (Enterprise Gateway, Merlin, Platform Agents, Workflow Services, Business Functions)
- **I**: Open-source agent framework deep dive (Volcano/Kong, Mastra, CrewAI, AutoGen / Microsoft Agent Framework, Apache Burr, Dapr Agents, Haystack 2.x, Letta)
