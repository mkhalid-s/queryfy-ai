# Code Review: Phase 1 UI Redesign — LeanChatBubble + ArtifactPane + ChatContainer wiring

**Date:** 2026-05-01
**Reviewers:** 14 perspectives (local Claude agents, 2 passes × 7) — security-reviewer, architect, ops-reviewer, chief-programmer, devils-advocate, testability-reviewer, requirements-analyst
**Scope:** Branch `cleanup/strip-audit-tags-from-code-comments` — `LeanChatBubble.vue` (new), `ArtifactPane.vue` (rewritten), `ChatContainer.vue` (modified), `AppShell.vue` (modified)

## Summary

Phase 1 introduces a lean analyst-mode chat surface (`LeanChatBubble`) and a redesigned artifact pane with tabs, wiring both through `ChatContainer` and `AppShell`. The architecture is sound and the visual direction is clean. Six P0 issues must be fixed before merge: two are silent-degradation regressions explicitly forbidden by `frontend/CLAUDE.md`, one breaks the pane on mobile, one corrupts time-travel UX, and two involve broken state logic. Ten P1 issues cover lost capabilities, missing accessibility, and fragile code.

---

## P0 — MUST FIX (6 issues)

### P0-1: Tab fallback watcher only fires when `activeTab === 'chart'`
**Consensus:** 12/14 perspectives
**Flagged by:** architect, chief-programmer, devils-advocate, requirements-analyst (both passes each)
**File:** `frontend/src/components/chat/analyst/ArtifactPane.vue` lines 428–435
**What's wrong:** The watcher that switches the active tab when a new message is selected is gated on `activeTab === 'chart'`. If the user is on the Data or SQL tab when they click a different turn, the tab does not update — e.g., a SQL-only turn while viewing Data keeps showing an empty Data panel.
**Why it matters:** Core time-travel UX is broken for the majority of tab states. Clicking through conversation history shows stale/empty content.
**Fix:** Remove the `activeTab === 'chart'` guard entirely. The watcher should always call `selectBestTab()` when `selectedMessage` changes.

---

### P0-2: `ran_without_question_anchor` narrator state missing from `noInsightsMessage`
**Consensus:** 9/14 perspectives
**Flagged by:** requirements-analyst, architect, chief-programmer (both passes)
**File:** `frontend/src/components/chat/analyst/ArtifactPane.vue` lines 367–376
**What's wrong:** `noInsightsMessage` handles `skipped_no_llm_config` and `ran_but_empty` but `ran_without_question_anchor` falls through to `null`, causing a silent blank insights panel — the exact pattern banned by `frontend/CLAUDE.md`.
**Why it matters:** `frontend/CLAUDE.md` explicitly lists all three narrator states and says "Do NOT reintroduce the silent-blank-section behaviour." This is a direct regression of a documented rule.
**Fix:** Add a branch for `ran_without_question_anchor` returning an info-tone message object (e.g. title "Analysis without question context", message "Insights may be generic — ask a specific question for targeted analysis").

---

### P0-3: `LeanChatBubble` has no fallback when narrator is skipped and insights are empty
**Consensus:** 8/14 perspectives
**Flagged by:** requirements-analyst, chief-programmer, security-reviewer (both passes)
**File:** `frontend/src/components/chat/LeanChatBubble.vue` lines 35–52
**What's wrong:** When `insights=[]` and the narrator was skipped, the bubble renders answer text only with no fallback. `frontend/CLAUDE.md` mandates an explicit fallback in this case.
**Why it matters:** Silent degradation — user sees no signal that statistical analysis was substituted for business narrative. This defeats the analyst-mode hardening work done across 8 backend PRs.
**Fix:** Add a `narratorStatus` computed (reads `content.narrator_status`); render a small inline degradation note below the answer when `insights` is empty and `narratorStatus` is set.

---

### P0-4: Mobile <960px — "View" button is a dead interaction
**Consensus:** 7/14 perspectives
**Flagged by:** requirements-analyst, ops-reviewer, devils-advocate (both passes)
**File:** `frontend/src/components/layout/WorkspaceSplit.vue` (pane hidden at <960px); `frontend/src/components/chat/LeanChatBubble.vue` lines 55–65
**What's wrong:** Below 960px, `WorkspaceSplit` hides the artifact pane. The "View" button still renders and emits `select-turn` but nothing becomes visible. Tapping "View" silently does nothing.
**Why it matters:** Active misleading affordance on mobile.
**Fix:** Hide "View" below 960px via CSS (`@media (max-width: 960px) { .turn__action--view { display: none; } }`), or implement a mobile artifact drawer.

---

### P0-5: Auto-follow unconditionally overwrites `selectedTurnId`, breaking time-travel
**Consensus:** 6/14 perspectives
**Flagged by:** architect, devils-advocate, requirements-analyst (both passes)
**File:** `frontend/src/stores/conversation.js` line ~255 (new-turn auto-advance)
**What's wrong:** When a new AI turn streams in, the store unconditionally sets `selectedTurnId` to the latest turn. If the user clicked an earlier turn to inspect it, the streaming turn steals focus mid-inspection.
**Why it matters:** The click-a-turn → pane-updates flow is the primary UX of the split-pane. Auto-follow breaking it during active generation makes historical inspection impossible.
**Fix:** Only auto-advance `selectedTurnId` when it was already pointing at the previous latest turn (i.e., no explicit historical selection was made).

---

### P0-6: `hasArtifact` returns false for error/cancelled turns — pane shows welcome state
**Consensus:** 6/14 perspectives
**Flagged by:** chief-programmer, requirements-analyst, devils-advocate (both passes)
**File:** `frontend/src/components/chat/analyst/ArtifactPane.vue` `hasArtifact` computed
**What's wrong:** `hasArtifact` only returns true for `sql || chart || rawResult || raw_result || insights.length > 0`. Error (`content.error`) and cancelled (`content.cancelled`) turns return false, so the pane shows the "Ask anything…" welcome state instead of the error.
**Why it matters:** Error information is silently hidden when users click errored turns.
**Fix:** Add `c.error || c.cancelled` to `hasArtifact`; add a corresponding error/cancelled display state in the pane body.

---

## P1 — SHOULD FIX (10 issues)

### P1-1: `isGenerating` expression has operator-precedence fragility and stale state on cancellation
**Consensus:** 5/14 perspectives
**Flagged by:** chief-programmer, testability-reviewer (both passes)
**File:** `frontend/src/components/chat/ChatContainer.vue` lines 112–113
**What's wrong:** `isExecuting && index === conversation.length - 1 || (message.content?.isGenerating === true)` is accidentally correct but will be misread in future edits. Also `isGenerating` persists on cancelled turns.
**Fix:** Add explicit parentheses; clear `isGenerating` flag on cancellation in the store.

---

### P1-2: `AppShell.vue` mutates Pinia store ref directly
**Consensus:** 5/14 perspectives
**Flagged by:** architect, chief-programmer (both passes)
**File:** `frontend/src/components/layout/AppShell.vue` line 52
**What's wrong:** `@select-turn="conversationStore.selectedTurnId = $event"` writes directly to a store ref instead of through an action.
**Fix:** Add `setSelectedTurnId(id)` action to the conversation store and call that instead.

---

### P1-3: `precedingUserQuestion` is O(N²) during streaming re-renders
**Consensus:** 4/14 perspectives
**Flagged by:** architect, chief-programmer (both passes)
**File:** `frontend/src/components/chat/ChatContainer.vue`
**What's wrong:** `precedingUserQuestion(index)` walks backward through the conversation array on every render for each AI message — O(N²) during streaming.
**Fix:** Precompute a `Map<messageId, userQuestion>` as a `computed` from the conversation array.

---

### P1-4: Lost capabilities — feedback, export, copy, stop not wired to `LeanChatBubble`
**Consensus:** 4/14 perspectives
**Flagged by:** requirements-analyst, ops-reviewer (both passes)
**File:** `frontend/src/components/chat/LeanChatBubble.vue`
**What's wrong:** `AIResponseCard` exposed feedback, export, copy-rows, stop, toggle-results, toggle-chart. `LeanChatBubble` only has View/Why/Run.
**Fix:** Decide which actions belong in the bubble vs. pane toolbar. At minimum feedback belongs in the bubble; export can live in the pane toolbar.

---

### P1-5: Defensive-defaults pattern missing in new components
**Consensus:** 4/14 perspectives
**Flagged by:** chief-programmer, security-reviewer (both passes)
**File:** `frontend/src/components/chat/LeanChatBubble.vue`; `frontend/src/components/chat/analyst/ArtifactPane.vue`
**What's wrong:** `frontend/CLAUDE.md` mandates `safeSeverity`, `safeTitle`, `safeDescription` computeds with fallbacks. Neither new component follows this — a malformed insight with `undefined` severity will crash on `.toUpperCase()`.
**Fix:** Add safe computed wrappers with string fallbacks for all optional insight fields.

---

### P1-6: `severityRank` returns 0 for absent severity — valid insights silently hidden
**Consensus:** 4/14 perspectives
**Flagged by:** chief-programmer, requirements-analyst (both passes)
**File:** `frontend/src/components/chat/LeanChatBubble.vue` `severityRank` lines 213–219; `headlineInsight` lines 144–150
**What's wrong:** `headlineInsight` suppresses any insight where `severityRank <= 0`. An insight with no `severity` field gets rank 0 and is hidden even with real content.
**Fix:** Treat absent/unknown severity as 'low' (rank 1) so real insights surface.

---

### P1-7: ChartView lazy-load failure is silent — no `errorComponent`
**Consensus:** 3/14 perspectives
**Flagged by:** ops-reviewer, testability-reviewer (both passes)
**File:** `frontend/src/components/chat/analyst/ArtifactPane.vue` `defineAsyncComponent` for ChartView
**What's wrong:** No `errorComponent` or `loadingComponent`. If the chunk fails to load, the Chart tab shows nothing.
**Fix:** Add `errorComponent` showing "Chart unavailable" and a `loadingComponent` spinner/skeleton.

---

### P1-8: Tab strip missing `role="tabpanel"`, `aria-controls`, arrow-key navigation
**Consensus:** 3/14 perspectives
**Flagged by:** requirements-analyst, security-reviewer (both passes)
**File:** `frontend/src/components/chat/analyst/ArtifactPane.vue` tab strip and panels
**What's wrong:** Tab buttons have `role="tab"` and `aria-selected` but panels lack `role="tabpanel"` and `aria-labelledby`. Arrow-key navigation not implemented (WCAG 2.1 §4.1.2).
**Fix:** Add `role="tabpanel"`, `aria-labelledby` on panels; add `@keydown.left`/`@keydown.right` on the tab strip container.

---

### P1-9: Streaming UX — pane shows stale/blank content while rail shows "Thinking…"
**Consensus:** 3/14 perspectives
**Flagged by:** requirements-analyst, devils-advocate (both passes)
**File:** `frontend/src/components/chat/analyst/ArtifactPane.vue`; `frontend/src/stores/conversation.js`
**What's wrong:** Auto-follow (P0-5) switches the pane to the empty in-progress turn while the rail shows "Thinking…" — jarring disconnect.
**Fix:** During generation, keep the pane on the previous completed turn until the new turn has substantive content, or show a loading skeleton.

---

### P1-10: Zero test coverage on `LeanChatBubble` and rewritten `ArtifactPane`
**Consensus:** 3/14 perspectives
**Flagged by:** testability-reviewer (both passes)
**File:** `frontend/src/components/chat/LeanChatBubble.vue`; `frontend/src/components/chat/analyst/ArtifactPane.vue`
**What's wrong:** Both components have zero Vitest tests. Critical paths — tab switching, `headlineInsight` ranking, narrator fallback, `hasArtifact` edge cases — are untested.
**Fix:** Add unit tests for: all three `noInsightsMessage` narrator states, severity ranking edge cases, `hasArtifact` with error/cancelled turns, `selectBestTab` priority logic.

---

## P2 — RECOMMENDED (3 issues)

### P2-1: "Why" button emits `open-reasoning` but no reasoning display is wired
**Consensus:** 2/14
**File:** `frontend/src/components/chat/LeanChatBubble.vue` line 68
**Fix:** Either wire a reasoning drawer/modal or hide the button until the display component exists.

### P2-2: No loading skeleton in Data tab while rows are being fetched
**Consensus:** 2/14
**File:** `frontend/src/components/chat/analyst/ArtifactPane.vue` Data tab
**Fix:** Show skeleton rows when `rawResult` is absent and the selected turn is still generating.

### P2-3: Follow-up chips missing `type="button"` and keyboard submit confirmation
**Consensus:** 2/14
**File:** `frontend/src/components/chat/analyst/ArtifactPane.vue` follow-up section
**Fix:** Confirm chips emit on `@keydown.enter`; add `type="button"` to prevent accidental form submission.

---

## P3 — MINOR (2 issues)

### P3-1: Thinking-dots animation flashes at full opacity before starting
**File:** `frontend/src/components/chat/LeanChatBubble.vue` `.dots span` keyframe
**Fix:** Add `animation-fill-mode: both` to prevent the initial opacity flash.

### P3-2: `turn__meta` row-count right-alignment may break on narrow viewports
**File:** `frontend/src/components/chat/LeanChatBubble.vue` `.turn__meta`
**Fix:** Verify `margin-left: auto` works inside `.turn__affordances` flex context at 320px viewport width.

---

## Positive Observations

- **Security clean:** No `v-html`, `innerHTML`, or `eval` in new code. SQL is mustache-bound. No URL/href construction from server-supplied fields. XSS attack surface is zero.
- **Pinia reactivity correct:** `storeToRefs()` used correctly in all components that destructure store state.
- **camelCase + snake_case tolerance:** Content readers check both forms (`rawResult || raw_result`, `agentSteps || agent_steps`). Both SSE and REST payloads handled.
- **ChartView import path fixed:** `../../ChartView.vue` resolves correctly from `chat/analyst/`.
- **ESLint baseline held:** `} catch {` keeps the warning count at the 3-warning baseline.
- **Tab strip visual design:** Chart/Data/SQL/Insights tabs with `fade-swap` transitions is a focused improvement over the old card-per-message layout.
- **`headlineInsight` ranking:** Correct for the happy path — highest non-info insight surfaces in the rail, info-tier stays in the pane.
- **`handleSelect` interactive-child guard:** Click propagation guard correctly prevents double-firing when affordance buttons are clicked inside a turn.
