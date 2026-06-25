# Pre-merge Review — Tier A rollout

**Date:** 2026-05-11 (7-perspective) and 2026-05-11 (12-perspective)
**Branch:** `plan/audit-2026-05-rollout`
**Scope:** Consolidated 9-item Tier A rollout (A1–A9) before merge to `main`. Two reviews ran against the same branch — a 7-perspective post-consolidation review, then a 12-perspective re-review after pre-merge gate commits.

This doc is the durable record. Detailed per-reviewer reports are in commit messages and review-transcript artifacts under `.claude/`; this file is the synthesis future sessions should read first.

---

## Pass 1 — 7-perspective review (2026-05-11 evening)

| Reviewer | Verdict | Key finding |
|---|---|---|
| A — Security | SHIP-WITH-FIX | Credential-leak regression-guard test missing (F8) — A4 sanitization is correct, but no test asserts the wiring stays put. |
| B — SRE | SHIP-WITH-CARVE-OUT | A8 MCP endpoint needs gating; no rate limiting; F1 cosign-verify enforcement missing. |
| C — Code quality | SHIP-WITH-FIX | Minor smells; no blockers. |
| D — Testing | SHIP-WITH-FIX | F8 not covered by tests; A8 has dispatch test but not a gate test. |
| E — Perf/UX | SHIP-WITH-FIX | Frontend bundle stable; no regressions. |
| F — Contrarian | DELAY | F20 acknowledged-broken (`MultiProcessCollector` not wired); 38 follow-ups in a 9-item umbrella is a triage-to-ship pattern. |
| G — Docs coherence | SHIP-WITH-FIX | PR-body / tracker / audit-doc drift; F36 was a wrong claim. |

**Consensus pre-merge gate** (A + D + F converged on the same load-bearing item):

- **F8** — Add parametrized regression test for credential leaks through tool errors. Landed as `backend/tests/smoke/test_f8_credential_leak_regression.py` (commit `071acd7`).
- **F35** — Gate A8 behind `MCP_ENDPOINT_ENABLED` env var, default off. Landed as `backend/app/api/mcp.py` conditional mount + smoke test (commit `dcc5464`).

---

## Pass 2 — 12-perspective re-review (2026-05-11 night, post-pre-merge-gate)

After Pass 1's gate commits, a deeper 12-perspective pass ran against the new HEAD (`071acd7`). All 12 reviewers were local subagents (no Bedrock dispatch), reading code in this repo.

| Reviewer | Verdict | Convergence with others |
|---|---|---|
| Security | SHIP-WITH-FIX | A1 SHA-pin claim partial (most `actions/*` + `docker/*` still symbolic — `docker/build-push-action@v6` is build-time RCE-equivalent). MCP `tools/call` has no per-route rate limit. |
| Code Quality | SHIP-WITH-FIX | **`GetTableSchemaCard.vue:46-52` TDZ** — `targetTable` references `parsed.value` before `parsed` is declared. (Converged with UX.) |
| Architect | SHIP-WITH-FIX | **MCP exposes all 18 ToolRegistry tools**, not the curated 5 the audit advertised. **`initialize` advertises `listChanged: false`** → freezes tool-name contract before Tier B refactors. |
| Performance | SHIP-WITH-FIX | `session_store.py:679` Redis `KEYS session:*` — O(N), blocks Redis on every session lifecycle. F20 `MultiProcessCollector` confirmed unwired. |
| UX/Frontend | SHIP-WITH-FIX | **`AgentTimeline.vue` uses `:key="index"`** → wrong card reused mid-stream on retry. Accessibility gaps on streaming surface. (Converged with code-quality on TDZ.) |
| SRE/DevOps | SHIP-WITH-FIX | **`rows_ref` (= `result:{session_id}:{query_id}` — IDOR boundary credential) logged at INFO** in `cache_inspection_tools.py`. **`MCP_ENDPOINT_ENABLED` is module-load-time** not a runtime kill-switch. `gh-pages.yml` retains top-level `contents: write` + `id-token: write`. |
| Testing | SHIP-WITH-FIX | F8 source-grep tests defeated by `import as` rename; F9 xfail tests need `strict=True`; no end-to-end F8+A8 intersection test. |
| Docs Coherence | SHIP-WITH-FIX | Tracker line 164 stat stale; F37 test count drift; audit doc missing "Closed by Tier A" annotations. |
| Contrarian | **DELAY** | F8 was caught by pre-merge gate, not by the 7-reviewer pass — what else was missed? F20 is acknowledged-broken; observability ships as a lying dashboard. Headline retrieval P0s are NOT in branch. |
| Critic | SHIP-BUT-RETHINK-SEQUENCING | Retrieval P0s (the deepest audit finding) are still all open. A7 harness isn't wired into CI. Git cadence is burst-and-stall. |
| Integration | SHIP-WITH-FIX | A4 + A8 error formats agree, but **A9 parsers have no `"Error executing"` branch** → tool errors fall through to GenericToolCard. A5 gauge seed runs in lifespan() but A8 router mounts at import. |
| Shipping Readiness | SHIP-WITH-FIX → **CI BLOCKER** | `TestCassandraDerivation` missing `allow_local_lock` autouse fixture → CI red under xdist parallel. 3 checks failing. |

**Total: 11× SHIP-WITH-FIX, 1× DELAY.**

---

## Pre-merge fixes landed (in order)

| Commit | What | Reviewer source |
|---|---|---|
| `dcc5464` | A8 carve-out — `MCP_ENDPOINT_ENABLED` gate, default off | Shipping-readiness (Pass 1) |
| `071acd7` | F8 regression test + A8 gate smoke test (12 new tests; 8 pass + 3 xfail F9 catalogue, plus 4 gate tests) | Security + Testing + Contrarian (Pass 1) |
| `77c27bb` | `TestCassandraDerivation` `allow_local_lock` autouse fixture — unblocks CI | Shipping-readiness (Pass 2) |
| `44c5683` | 4 real-bug fixes: `GetTableSchemaCard.vue` TDZ; `AgentTimeline.vue` stable key; `cache_inspection_tools._safe_rows_ref()`; `flex-wrap: wrap` on 2 cards | Code-quality + UX + SRE convergence (Pass 2) |

---

## Pass 3 — 12-perspective re-review (2026-05-12, delta scope on `35bed58`)

After Pass 2's closeout commits + the F47 review-consensus fix bundle, a third 12-perspective pass ran scoped to commit `35bed58` only. Confirmed once again that **the convergence pattern is the highest-signal output**: the same bug class F47 fixed for `active_sessions` and `circuit_breaker_state` was repeated in the same commit's new `mcp_enabled` gauge — caught by 5 independent reviewers and fixed in `bff60f1`.

| Reviewer | Verdict | Key finding |
|---|---|---|
| Security | SHIP | All claimed closures verified; P2 caught `mcp_enabled` missing multiproc mode |
| Code Quality | SHIP-WITH-FIX | JSON silent-fallthrough in `MCP_EXPOSED_TOOLS` validator → literal `'[bad json'` tool name; bare `except Exception` should be `except AttributeError` |
| Architect | "surface polish with one real fix" | `mcp_enabled` is a parallel source of truth — will desync if anyone adds a runtime toggle path; Chroma/Qdrant branches now duplicate-shaped, refactor opportunity |
| Performance | SHIP | Qdrant executor wrap correct and consistent with existing Chroma pattern |
| UX/Frontend | SHIP | Zero frontend touches; verified clean |
| SRE/DevOps | SHIP-WITH-FIX | Same `mcp_enabled` multiproc finding; `recall@k` regex literal doesn't match the body's `recall@k harness` mention; cold-start floor on `ResultCacheHitRateLow` defensible at 0.1 ops/sec |
| Testing | SHIP-WITH-FIX | F47 bundle shipped zero new tests for 5 behaviour changes |
| Docs Coherence | SHIP-WITH-FIX | PR body still stale; F47 line citation off by 7; Pass-3 addendum (this section) needed |
| Contrarian | **SPLIT-THE-BRANCH** | "F20 recurring in the same commit that claims to fix F20" — bundle pattern defeats bisection; umbrella grown 50 → 51 commits during this review session alone |
| Critic | **SHIP-NOW (3rd time)** | "`35bed58` is not the problem — the willingness to add `35bed58` to this branch instead of to main is the problem" |
| Integration | SHIP-WITH-FIX | Same `mcp_enabled` multiproc bug — Integration's BLOCK-class for the alert it exists to serve |
| Shipping Readiness | SHIP-WITH-FIX | CI red — but on the procedural recall@k gate (body language mismatch), not on code; mypy + tests + build all green locally |

### Pass-3 fixes landed in `bff60f1`

| Issue | Reviewer convergence | Fix |
|---|---|---|
| `mcp_enabled` gauge missing `multiprocess_mode` | **5 reviewers** (Security + Architect + Contrarian + Integration + SRE) | Wrapped in same `if PROMETHEUS_MULTIPROC:` pattern as `active_sessions`/`circuit_breaker_state` with `multiprocess_mode="livemax"` |
| `MCP_EXPOSED_TOOLS` JSON silent fallthrough | Code Quality + Architect | Validator now raises `ValueError` on bracket-prefixed input that fails JSON parse or returns non-list |
| Bare `except Exception` around gauge seed | Code Quality | Narrowed to `except AttributeError` (the only case the comment claimed to cover) |
| F47 bundle shipped zero new tests | Testing P0 + Contrarian | Created `backend/tests/smoke/test_f47_review_consensus_smoke.py` with 15 tests pinning load-bearing invariants (CSV/JSON parse, IDOR predicate in SQL WHERE, alert YAML parse, gauge multiproc-mode source check) |
| PR body procedural gate failure (`recall@k` literal) | Shipping Readiness P0 | PR #69 body updated with explicit "no recall impact" line |

### Pass-3 specific lessons

5. **"Bug class repeats in the bug-fixing commit" is a real failure mode.** The F47 bundle correctly fixed `multiprocess_mode` for two existing gauges, then added a new gauge missing the same mode. The convergence-on-known anti-pattern means reviewers caught the named issues (F20, MultiProcessCollector wiring) but the new gauge slipped through because nobody asked "do we have any NEW gauges that should also have this?" *Add a pre-commit checklist item: when fixing a class of bug, audit the same commit for new instances of the class.*

6. **One commit, nine fixes = no per-fix rollback.** The F47 bundle paired CI unblock + IDOR fix + alert rewire + validator + docs in a single commit. If the alert query regresses on staging, `git revert 35bed58` also reverts the IDOR fix and the CI unblock. Per-phase commits (as in this Pass-3 addendum's six follow-ups) are the right granularity for a release umbrella.

---

## Findings deferred — scheduled, not fixed in Tier A

Post-merge windows defined in `docs/PLAN-TRACKER.md`:

- **Window 1 — Tier A.5 closeout:** F1 (cosign verify), F20 (MultiProcessCollector), F9 (sanitizer extensions — closed 2026-05-12), Prometheus alerts wired, A1 SHA-pin completion (deferred — needs SHA-lookup pass).
- **Window 2 — MCP hardening before flag-flip:** F34 (rate limit), `MCP_EXPOSED_TOOLS` allowlist, auth on `tools/list` + manifest, runtime kill-switch.
- **Window 3 — Tier B gate-then-ship:** wire `benchmarks/retrieval/harness.py` into required GHA check; ship B2 (`get_column_context` query-awareness) first.
- **Window 4 — Doc chaser:** this file, audit-doc closure annotations, tracker stat updates (closed 2026-05-12).

---

## Lessons for future review cycles

1. **F8 escaped 4 deep reviewers in Pass 1.** Reviewers were reading diffs in isolated worktrees; nobody actually ran an end-to-end credential through the sanitizer. Future pre-merge review must include at least one reviewer who exercises load-bearing paths against real code, not just reads diffs.
2. **The TDZ bug in `GetTableSchemaCard.vue` only triggers when `args.table_name` is absent — a path the test fixtures consistently include.** Defensive test fixtures should cover the documented-degradation contract, not just the happy path.
3. **The CI blocker (`TestCassandraDerivation`) wasn't introduced by Tier A** — it's a pre-existing test-isolation defect from `a74caea`. Branch protection caught it; the local `pytest tests/smoke/` run did not, because xdist defaults differ from local.
4. **The convergence pattern is the highest-signal output.** When 3+ reviewers independently flag the same line, it's load-bearing. When 1 reviewer flags it, it's worth tracking but not always merge-blocking.
