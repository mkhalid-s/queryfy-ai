# Backend — area-specific guidance

Loads on-demand when Claude works in `backend/`. Captures area-specific patterns not covered in the root `CLAUDE.md`. Keep under 200 lines.

## Tool handler conventions (`app/services/tools/`)

- Every analyst-mode tool handler returns a JSON-serialisable dict whose content the LLM sees verbatim as a `ToolMessage`. Never return raw exception strings — route through `ErrorSanitizer.sanitize_error()` from `app/services/security.py` first. Otherwise DB error strings, URLs with credentials, and stack-trace fragments leak into the tool result the LLM sees, and the LLM can emit them downstream despite the SYSTEM_PROMPT voice rule.
- The schema `required: [...]` in `tools/definitions.py` is the **LLM-facing contract** (enforced at tool-call time). Python handler signatures keep parameters `Optional` with defaults so direct unit-test calls still work — the Python signature is the **test-facing contract**. Keep them aligned but not identical: add load-bearing params to both; the difference is the `Optional` default on the handler vs `required` on the schema.
- New load-bearing params (like `question=` on `execute_and_analyze`) belong in schema `required`, not just in the description's "always include" advisory. Voice rules in the prompt are advisory; schema is enforceable.

## `execute_and_analyze` observability

- Emits `narrator_status` + `insights_type` so the UI can distinguish "no patterns found" from silent narrator degradation. Four states: `ran_successfully`, `ran_but_empty`, `skipped_no_llm_config`, `ran_without_question_anchor`.
- Response payload already carries metadata signalling sampling, truncation, caching (`rows_ref`, `rows_cached`, `rows_truncated`, `rows_truncated_reason`) and chart unavailability (`chart_unavailable_reason`). Add to this pattern rather than bypassing it when introducing new signals.

## Result cache patterns (`app/services/result_cache.py`)

- Redis-first with in-memory LRU fallback (cap 200 entries); `astore` is wrapped in `asyncio.wait_for(..., 10.0)` so a slow Redis doesn't stall tool handlers. On cache failure, surface `rows_ref=None` + `rows_truncated=True` — never block the tool.
- IDOR boundary lives at the API layer (`api/queries.py:630–793`) via `hmac.compare_digest` on the `result:{session_id}:` key prefix. Tool handlers (`get_cached_rows`, `inspect_cached_result`) trust the agent context; don't duplicate the check there.
- NaN/Inf scrubbing at serialisation time in `result_cache.py:63–82`. Required for the frontend's `JSON.parse` not to throw `SyntaxError`. Covered by `test_phase4_fixes.py::test_nan_in_row_becomes_null`.

## Prompt + agent conventions

- SYSTEM_PROMPT in `app/services/react_agent.py` is principle-based (57 lines post-2026-04-22 diet). Do NOT reintroduce per-tool prescriptive guidance unless a behavioural regression is observed — tool descriptions carry per-tool when/why.
- Hard test constraint: `get_cached_rows`, `inspect_cached_result`, and one of `follow-up` / `those results` / `previous query` / `ROUTING RULE` must remain as literal substrings in SYSTEM_PROMPT (asserted in `test_phase4_fixes.py::TestSystemPromptAdvertisesCacheTools`).

## Testing under constrained environments

- **Run tests via `bash backend/scripts/run-tests.sh`**. The script auto-rebuilds a broken `backend/venv` (the bundled symlink is sometimes a host-pyenv path that doesn't resolve in dev containers). Prefers `uv` when available (already installed in this dev image), falls back to `python3 -m venv`. Pass any pytest args after the script: `bash backend/scripts/run-tests.sh tests/smoke -v`. Use `--skip-rebuild` after first run for speed.
- Smoke tests live in `backend/tests/smoke/` — fast, mock-only, no DB / no network. Useful canary; run them before any non-trivial change. They caught a Wave 1 production bug (typing.Any import order in `conversation_tools.py`) that ast.parse + extract-and-simulate alone missed.
- `FakeContext` in tests typically lacks `llm_config`. Handler code should use `getattr(context, "llm_config", None)` rather than direct attribute access, so it doesn't `AttributeError` under mock — this is what lets `narrator_status = "skipped_no_llm_config"` branch work in tests without special-casing.

## Wall-clock budget tuning

`AGENT_WALL_CLOCK_BUDGET_SECONDS` (default 600 s) caps overall analyst-mode agent runs. Tune per deployment shape:

- **OLTP / reporting** (Postgres, MySQL): keep default 600 s or drop to 300 s. Most queries finish in seconds; legitimate runs over 60 s are rare.
- **Analytical batch** (BigQuery, Snowflake without warmed warehouse): 1200–1800 s. Cold-warehouse queries can run 5+ min on first hit.
- **Data lake** (Trino, Athena, Hive): match the per-tool timeout × max_iterations / 2. The default per-tool timeout is 300 s for these (`TOOL_TIMEOUT_BY_DB` in `react_agent.py`). At 10 max_iterations that's 50 min worst case; budget at 1800 s (30 min) lets ~6 iterations of slow tools complete and stops the pathological case.
- **Disable** by setting to 0 — operator escape hatch. Use only with strict per-tool timeouts in place.

## PII over-masking workaround

Wave 1 PII redaction uses OR-semantics across the connection's `ColumnDescription` set: if any table flags column X as `is_pii=True`, the column gets masked everywhere. So a legitimately non-PII `audit_logs.email` is masked because `users.email` is flagged.

Two ways to fix in production today:

1. **Explicit override**: in Context Studio, add a `ColumnDescription` for `audit_logs.email` with `is_pii=False`. The explicit entry suppresses the heuristic and the OR-aggregation honours the False on a per-column-name basis (note: still per-name, not per-table — Wave 2C closes that gap with SQL parsing).
2. **Rename**: avoid the column-name collision (`users.email_address` vs `audit_logs.email`). Heavy-handed; only viable for greenfield schemas.

Wave 2C will eliminate the false positive entirely by parsing the SQL to determine which table(s) the query references and narrowing the dictionary lookup. Until then, option (1) is the documented workaround.

## Style

- All endpoints `async`. Business logic belongs in `app/services/`; keep routes thin.
- Pydantic for validation. Add docstrings to new `ChatResponse` fields that future sessions need to understand (e.g., `narrator_status` is explained inline so agents don't have to trace it).
- Linting / type-check: `ruff check .` and `mypy app/` from `backend/`.
