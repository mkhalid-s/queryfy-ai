# Open-PR Deep-Review Summary — 2026-05-19

## Final tally across the 17 open PRs

**14 MERGE-NOW** • **1 FIX-FIRST** • **2 STRATEGIC HOLD**

| # | Verdict | Type | One-line |
|---|---|---|---|
| **#81** | MERGE-NOW | npm-patch | `vue` 3.5.31→3.5.34 |
| **#82** | MERGE-NOW | npm-patch | `@iconify/vue` 5.0.0→5.0.1 |
| **#78** | MERGE-NOW | pip-minor | `psycopg` floor `>=3.1.0`→`>=3.3.4` |
| **#83** | MERGE-NOW | npm-dev-patch | `@vitest/coverage-v8` 4.1.2→4.1.6 (CI noise is unrelated runner issue) |
| **#84** | MERGE-NOW | docker | nginx-unprivileged 1.29→1.31-alpine |
| **#80** | MERGE-NOW | npm-dev | `jsdom` 28→29 — only breaker is Node 22.13+ floor; CI Node-22 satisfies |
| **#74** | MERGE-NOW | pip-dev | `ruff` 0.1→0.15 — floor bump, no new default rules; `ruff check app/` already clean |
| **#75** | MERGE-NOW | pip | `structlog` 24→25 — floor bump, zero exposure for this codebase; CI red is unrelated runner pod failure |
| **#70** | MERGE-NOW | docker | `node` 25→26-alpine — Node 25 EOL'd, image exists; toolchain has no engine ceiling |
| **#71** | MERGE-NOW | gh-actions | `docker/setup-qemu-action` 3→4 — runtime-only Node-24 bump; peers compatible |
| **#72** | MERGE-NOW | gh-actions | `actions/deploy-pages` 4→5 — Node 20→24; `upload-pages-artifact@v3` + `configure-pages@v4` compatible |
| **#73** | MERGE-NOW | gh-actions | `actions/download-artifact` 7→8 — only used at 2 release.yml tarball sites; ESM/hash-mismatch changes don't apply |
| **#76** | MERGE-NOW | pip | `langgraph` 1.1.10→1.2.0 — additive; F71 already neutralized the `get_type_hints`/forward-ref footgun |
| **#77** | MERGE-NOW | pip | `langgraph-checkpoint-postgres` 1.0→3.1 — required co-version for #76; breaking changes (ltree-in-store, JSONB metadata, typed-serializer allow-list) all map to code paths we don't use |
| **#79** | **FIX-FIRST** | npm | `vite` 7→8 — Vite 8 swapped Rollup→Rolldown which rejects the object form of `manualChunks` in `frontend/vite.config.js:38-49`; convert to function form and CI goes green |
| #69 | STRATEGIC HOLD | umbrella | `plan/audit-2026-05-rollout → main` — owner-hold per session policy |
| #57 | STRATEGIC HOLD | feature | `redesign/split-pane-spike → main` — deferred per `PLAN-TRACKER.md:65` until Tier B retrieval stabilizes |

## Cross-PR dependencies

- **#76 and #77 must merge together** — langgraph 1.2.0 pins `langgraph-checkpoint>=4.1.0,<5.0.0`, which only checkpoint-postgres 3.x satisfies. Don't merge one without the other.
- **The 5 SAFE-TO-MERGE patches** (#78, #81, #82, #83, #84) have no cross-deps; merge in any order.
- **#71 / #72 / #73 (gh-actions majors)** — independent of each other; could be a batch.

## Recommended merge order

1. **Patches batch** (no risk, no cross-deps): #78, #81, #82, #84, #83
2. **Dev-only batch**: #80 (jsdom), #74 (ruff)
3. **Infra batch**: #70 (node 26), #71/#72/#73 (gh-actions)
4. **Backend batch (atomic)**: #75 (structlog), then #76+#77 (langgraph + checkpointer, same merge or back-to-back)
5. **After F75 fix**: re-eval #79 (vite 8)

## What's not closed by this triage

- **#79 vite 8** — needs a 1-line fix to `frontend/vite.config.js` `manualChunks` (object form → function form). One commit, one PR, then merge.
- The 8 CI failures observed on individual PRs are mostly the same self-hosted-runner-pod-unhealthy issue — not real test failures. Worth a single CI re-run-all sweep before merging the batch.
