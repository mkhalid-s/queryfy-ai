# UI redesign — research + recommended information architecture (2026-04-28)

**Status**: research only; no code changes.
**Trigger**: User feedback that the current UI feels "shabby... messy and stuffed forcefully to make it conversational... not aesthetic, simple, or easy."
**Scope**: redesign the chat / SQL / data / chart / insights surfaces. Backend untouched. Framework choice (Vue vs alternate UI framework) is a separate question parked in `memory/project_ui_framework_migration_parked.md`.

---

## Method

Three parallel research agents across three reference clusters:

1. **NL-to-data competitive scan** — 10 products in the conversational analytics space, with an emphasis on documented redesigns and public design retrospectives. Focused on direct analogs (WrenAI, Hex, Cortex Analyst, ThoughtSpot Spotter, Vanna.ai 2.0).
2. **LLM chat + artifact patterns** — 10 products in the broader "chat with rich output" category. Cursor, Claude.ai Artifacts, ChatGPT Canvas, v0, Bolt, Lovable, Replit Agent, Continue.dev, Copilot Chat, JetBrains AI.
3. **Cognitive-load + IA fundamentals** — Nielsen Norman Group, Stephen Few, peer-reviewed papers, the 2026 "Conversation Trap" article, the 2025 NLIDB user study (arXiv 2511.14718).

Citations are inline in each section. Sources confirmed via web search; date stamps captured where the source provides them.

---

## Section 1 — What the products that solved this actually did

### Direct analog: WrenAI (open-source NL-to-SQL, closest to nl2sql-app)

Repository: github.com/Canner/WrenAI. Stack: Next.js + Apollo GraphQL + AI Service + Wren Engine.

**Layout**: Home is a ChatGPT-like prompt page. Each "Thread" opens a **dedicated thread view** with the question at top, then a **tabbed result panel: View SQL / View Result / View Chart**. Chat history lives in a sidebar — the thread itself IS the artifact, not a chat bubble.

**Key takeaway**: SQL / data / chart are sibling tabs, never stacked vertically. This is the validated default for our exact shape.

### Hex Notebook Agent (June 2025 redesign — most relevant retrospective)

Source: hex.tech/blog/introducing-notebook-agent, learn.hex.tech/changelog/2025-06-25.

**Layout**: Persistent **right-sidebar agent**. The agent does NOT render outputs in the chat — it creates / edits SQL, Python, Markdown, Pivot, and Chart **cells** in the notebook. Per their changelog: "for quick syntax questions, brainstorming, or finding data."

**Key takeaway**: Chat is a **control surface**; the workspace is the artifact. Outputs become durable, editable, owned-by-the-user cells. **Strongest single retrospective signal we have** — Hex actively pivoted away from "outputs in chat."

### Vanna.ai 2.0 (open-source — also wrote this lesson)

Source: vanna.ai. Vanna 2.0 is a "complete rewrite focused on user-aware agents... streaming rich UI components instead of text/dataframes."

**Key takeaway**: V1 returned a SQL string + a dataframe + a Plotly figure as raw outputs in chat. V2 wraps each in **first-class typed components** with their own toolbars. They explicitly identified the "raw outputs in chat" failure and rewrote.

### Snowflake Cortex Analyst (Streamlit reference UI)

Source: docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst.

**Layout**: Per-message **collapsible** sections inside `st.chat_message`: SQL block, results dataframe, chart — each in its own collapsed expander. **SQL is editable inline.**

**Key takeaway**: Even within a single chat thread, **collapse by default**. Only the natural-language summary and the chart are first-class; SQL/data are one click away.

### ThoughtSpot Spotter (rebrand of Sage)

Source: thoughtspot.com/blog/introducing-spotter-ai-analyst.

**Layout**: Chat prompt + history panel + **separate Liveboard canvas**. Charts/tables render as Liveboard tiles, not chat-bubble children. Spotter is the agent; SpotterViz auto-builds dashboards as the output.

**Key takeaway**: Killed the "stuff in bubble" approach entirely; output materializes as a dashboard the user can pin / share / navigate independently. Mode (acquired by ThoughtSpot, GA early 2025) absorbed into Analyst Studio with the same separation.

### Tableau Pulse (replaced Ask Data)

Source: tableau.com/blog/tableau-pulse-and-tableau-ai. Pulse explicitly **replaced** Tableau Metrics + Ask Data.

**Key takeaway**: Tableau gave up on open-ended NL chat and pivoted to a **newsfeed of metric cards with per-metric Q&A**. Conversation is **scoped to a metric**, not free-form. Strong negative result on the open-chat-over-arbitrary-data approach.

### Power BI Q&A → Copilot

Source: learn.microsoft.com/en-us/power-bi/natural-language/q-and-a-intro.

**Key takeaway**: Microsoft is **deprecating Q&A in December 2026** in favor of Copilot for Power BI. The original "type-and-render-one-chart" model lost. Two BI giants (Tableau + Microsoft) independently retired their first-generation NL chat surfaces.

### Quadratic, Chat2DB, Julius AI (briefer — same pattern family)

- **Quadratic**: chat is a **right-panel assistant**; spreadsheet canvas is the artifact.
- **Chat2DB**: tabbed editor workspace (multi-tab IDE) + AI chat side panel.
- **Julius AI**: closest to current nl2sql-app — outputs inline in thread. They added a notebook canvas as a *parallel mode* for users who outgrew chat-only.

---

## Section 2 — Convergent patterns

Across the 10 NL-to-data products and 10 LLM-chat products, four patterns appear in 4+ products:

1. **Chat is a command surface; artifacts live elsewhere.** Hex (notebook cells), ThoughtSpot (Liveboard), WrenAI (thread view with tabs), Quadratic (spreadsheet), Chat2DB (tabbed editor), Cursor, Claude Artifacts, ChatGPT Canvas, v0, Bolt, Lovable, Replit. Universal across the modern leaders.

2. **Tabs / panels for SQL vs data vs chart, not stacking.** WrenAI, Cortex Analyst's reference UI, Vanna 2.0's component model, Chat2DB. SQL is collapsible / secondary; chart-or-table is primary.

3. **Right-sidebar agent is the dominant placement** when chat lives next to artifacts. Hex (June 2025), Quadratic, Claude Artifacts, ChatGPT Canvas — all use a 25–30% chat / 70–75% workspace split.

4. **Insights as natural-language summary, not insight cards.** Cortex Analyst "Summaries provide natural-language interpretations," Pulse "natural-language responses," Spotter prose answers. **Card-grid insights are rare in the leaders.**

5. **Agent timeline / reasoning trace is hidden by default.** Hex, ThoughtSpot, WrenAI all gate it behind a "Show steps" toggle. None default-show the ReAct trace.

### The promotion trigger spectrum

For analyst tools where every successful turn produces SQL+data+chart, the literature converges on **always promote** (matching v0, Bolt, Replit) — heuristic auto-promotion (Claude Artifacts >15 lines, Canvas >10 lines) is calibrated for general chat where most turns are conversational. Analyst chat is different: every turn produces structured output worth promoting.

---

## Section 3 — Cognitive-load principles applied

From NN/g, peer-reviewed UX research, and design literature:

1. **Progressive disclosure (Nielsen, 1995)** — Show primary information by default; defer secondary details to a subsidiary screen or expander. Map: collapse SQL, agent timeline, full insight list by default.
2. **Hybrid GUI + chat reduces cognitive load (NN/g)** — Replace prose with chips/buttons where possible. Map: follow-up suggestions as chip controls, not free-text rendered in the bubble.
3. **Explainable-AI is layered, not dumped (NN/g)** — Stack the "why" behind a reveal. Map: agent timeline as a chip on the message header, not a stacked block.
4. **Conversation rhythm vs artifact rhythm** — Chat reads linearly once; artifacts demand spatial stability and re-reading. Mixing them in one scroll forces the eye to constantly retune. Map: split-pane.
5. **Information overload threshold** — Empirical research (Royal Society Open Science) finds users disengage past ~30 simultaneously-relevant items per turn. Map: one chat turn must fit in one viewport-height before requiring expansion.
6. **Dashboards vs exploratory analytics (Few)** — Dashboards = at-a-glance monitoring; chat = exploratory dialog. NL2SQL is exploratory, so don't try to be a dashboard inside a chat bubble.
7. **The Conversation Trap (Designative, 2026)** — Defaulting to chat for structured / data-rich outputs is the core interaction-design mistake of the AI era. Prose is the wrong container for tabular reasoning.

### Identified anti-patterns (cited)

- **"Stuffed chat bubble" / kitchen-sink turn** — dumping every modality (prose + SQL + table + chart + insights + timeline + suggestions) into one card. Showcase pattern, not production pattern.
- **Repeated bordered/severity cards** — stacking visually identical bordered containers creates noise without hierarchy. (Stephen Few — *Information Dashboard Design*.)
- **Severity-color overuse** — coloring every insight high/medium/low destroys the signaling power of color.
- **Backscroll-to-reconstruct-state** — recent NLIDB user study (arXiv 2511.14718, 2025, 20 participants, SQL-LLM vs Snowflake) found this is the dominant UX failure mode.
- **Prose explanations without progressive layers** — explanations become walls of text.

---

## Section 4 — Recommended information architecture for nl2sql-app

Visualizable layout:

```
┌───────────────────────────────┬──────────────────────────────────────┐
│   CONVERSATION  (~38%)        │   ARTIFACT WORKSPACE  (~62%)         │
│                               │                                      │
│   Q1: Show top customers      │   ┌─[Chart] [Data] [SQL] [Insights] │
│       by Q3 revenue           │   │                                  │
│   ▸ Top 5 by revenue:         │   │   <chart for active turn>        │
│     Acme leads at 18%         │   │   header: "Q3 customers"         │
│     concentration risk.       │   │   meta: 8s · 1240 rows · cached  │
│     [Chart] [Why →]           │   │                                  │
│                               │   │   <Why drawer (collapsed)>       │
│   Q2: Break it down by region │   │      14 agent steps              │
│   ▸ EMEA holds 41% of total.  │   │                                  │
│     [Chart] [Why →]           │   └──────────────────────────────────┘
│   ▸ Active                    │
│                               │   <follow-up chips, sticky bottom>
│   ┌──────────────────────┐    │   [Compare to Q2] [Drill into EMEA]
│   │ Ask about your data… │    │   [Show YoY] [Pin this view]
│   └──────────────────────┘    │
└───────────────────────────────┴──────────────────────────────────────┘
```

### IA rules

**What stays in the chat thread (per turn):**
- The user's question
- A 1–3 line answer (LLM narrator output, prose only)
- A single headline insight (highest-severity finding) — one line, no card chrome
- Two affordances: `[View →]` (focuses artifact pane on this turn) and `[Why →]` (opens agent timeline drawer)
- Active-turn marker (subtle highlight, no border)

**What lives in the artifact workspace:**
- **Tabs**: Chart (default) · Data · SQL · Insights
- Chart tab: the chart for the focused turn, large, with its own toolbar (export, type-switch, annotate)
- Data tab: the table — paginated through the existing `rows_ref` cache
- SQL tab: read-only display + copy + (future) edit-and-rerun
- Insights tab: the structured list (concentration / trend / outlier / business_insight) — this is where the multi-card grid lives, NOT in chat
- Header strip: question · timestamp · row count · sampling-notice icon (click to expand) · narrator-status icon (click to see degraded-state explainer if present)
- Footer strip: follow-up suggestions as chips (sticky), pin-this-view, share

**What lives in a side drawer (right-edge, slide-out):**
- Agent timeline (full ReAct trace) — opens via `[Why →]` on the chat turn
- Tools used, durations, errors
- Anything operator-debugging — never default-visible

### Mapping to current Vue components

| Current component | After redesign |
|---|---|
| `AIResponseCard.vue` (the kitchen sink) | **Demoted** to chat-bubble shell (3 lines + 2 buttons). Most of its body moves to ArtifactPane. |
| `InsightCard.vue` (severity-tinted card) | **Stays**, but renders only inside the Insights tab, not in chat |
| `ContentTabs.vue` (SQL/Data/Chart inside a card) | **Promoted** to be the artifact pane root. Renamed `ArtifactPane.vue`. |
| `ChartView.vue`, `ResultsTable.vue`, `JsonTreeModern.vue` | Stay; consumed by ArtifactPane tabs |
| `AgentTimeline.vue` | Moves to a slide-out drawer (`AgentTimelineDrawer.vue`); collapsed by default |
| `FollowUpSuggestions.vue` | Becomes chip strip in artifact-pane footer |
| `DataQualityIndicator.vue` | Becomes an icon in the artifact-pane header (click to expand) |
| **NEW** `ArtifactPane.vue` | Top-level; receives `activeTurn` prop, hosts tabs |
| **NEW** `ChatThread.vue` | Top-level; lean message list with `selectedTurnId` state |
| **NEW** `AppShell.vue` | Top-level; CSS grid 38/62 split, responsive collapse to single column on narrow screens |

State: a single Pinia store augmentation — `conversation.selectedTurnId`. Click a chat turn → updates `selectedTurnId` → ArtifactPane re-renders for that turn. Past turns' artifacts come from the existing `rows_ref` cache (already implemented).

### Mobile / narrow-viewport collapse

Below ~900px, the split-pane collapses. Default to chat-only. Each chat turn shows a single `[View artifact →]` button that pushes a full-screen artifact pane on top. Back button returns. Mirrors how mobile email clients show list → detail.

---

## Section 5 — Phase plan

Five phases, each independently shippable. Total estimated effort: **3–5 weeks** for solo dev with LLM assist; **~2 weeks** for a small team. **Backend untouched** — the ChatResponse contract from Wave 1+2A already provides everything the new IA needs.

### Phase 1 — App shell + new chat thread (3–5 days)

- Create `AppShell.vue` with CSS grid split (38/62, configurable, mobile-collapse).
- Create `ChatThread.vue` — receives messages array, renders compact message bubbles. Wires selection state.
- Refactor existing `ChatContainer.vue` to render the lean message bubble (3 lines + 2 buttons + active marker). Keep all existing data flowing in for now.
- Right pane shows a placeholder ("Run a query to see the artifact").

Acceptance: existing functionality unchanged; UI is split-pane; selecting a turn updates a console.log.

### Phase 2 — ArtifactPane MVP (4–6 days)

- Create `ArtifactPane.vue` with 4 tabs (Chart / Data / SQL / Insights).
- Wire each tab to existing components: `ChartView.vue`, `ResultsTable.vue`, copy-friendly SQL block, `<InsightCard v-for>`.
- Header strip with question / timestamp / row count.
- Selected turn drives the pane.

Acceptance: typical analyst flow (ask question, see chart, switch to data tab, copy SQL) works. Old `AIResponseCard` becomes near-empty.

### Phase 3 — Footer chips + Why drawer (2–3 days)

- Follow-up suggestions as chip strip in artifact footer; click → fills input.
- "Why →" button on chat bubble opens `AgentTimelineDrawer.vue` (right slide-out, modal-ish).
- Sampling notice + narrator-status as info icons in the artifact header.

Acceptance: `AIResponseCard.vue` can be deleted (its responsibilities are dispersed).

### Phase 4 — Polish + responsive (3–4 days)

- Typography pass (one type scale, not two).
- Color audit — severity colors used only for genuine alerts.
- Spacing rhythm — design tokens consistent across panes.
- Mobile collapse + back-button.
- Keyboard shortcuts: `Esc` clears selection; `↑/↓` navigates turns; `Cmd+1..4` switches tabs.

Acceptance: visually clean; passes a 30-second "scan test" — user can see "what is this turn about" in <2 seconds.

### Phase 5 — Optional pinning + history (3–5 days, can defer)

- Pin a view → shows in a small "Pinned" strip at the top of the artifact pane.
- Compare two pinned views side-by-side (lightweight diff).
- Useful for analysts comparing two queries; fits the WrenAI "thread" pattern.

Acceptance: nice-to-have; ships when there's appetite. Not required for the core redesign.

---

## Section 6 — Open questions for decision

1. **Pane split ratio** — recommended 38/62 chat / artifact. Some products go 25/75 (Claude Artifacts) or 30/70 (Cursor). Open: do you want chat-heavy or artifact-heavy default? Configurable via drag-handle is a small extension.
2. **Default tab on artifact pane** — recommend Chart (matches WrenAI / Pulse / Cortex Analyst). If your users skew toward data-table-first, default to Data.
3. **Turn navigation model** — recommend **time-travel** (click a turn, pane shows that turn's artifact). Alternative: **versioned same artifact** (one artifact, scroll through versions like v0). For NL-to-SQL where each turn is conceptually a different query, time-travel is the better fit.
4. **Mobile parity goal** — full feature parity, or chat-only with a "view on desktop for full features" CTA? The latter is faster to build and matches the data-analyst persona (mostly desktop).
5. **Follow-up chips placement** — sticky in artifact footer (recommended) vs in chat thread under the active turn. Footer keeps chat clean.
6. **Old-message artifact retention** — keep all turns' artifacts available (current behaviour, since `rows_ref` cache holds them) vs only last N. Recommend keeping all; cache TTL handles eviction.

Each is a small decision that doesn't block Phase 1 starting, but shapes Phases 2–5.

---

## Section 7 — Reading list (for the user)

If you want to validate any of this independently before greenlighting, three articles capture 80% of the reasoning:

1. **NN/g — Progressive Disclosure**: <https://www.nngroup.com/articles/progressive-disclosure/>
2. **The Conversation Trap (Designative, 2026)**: <https://www.designative.info/2026/03/19/the-conversation-trap-why-defaulting-to-chat-might-be-the-biggest-interaction-design-mistake-of-the-ai-era/>
3. **How Anthropic Built Artifacts (Pragmatic Engineer, Simon Willison summary)**: <https://newsletter.pragmaticengineer.com/p/how-anthropic-built-artifacts> · <https://simonwillison.net/2024/Aug/28/how-anthropic-built-artifacts/>

For the closest analog to nl2sql-app, look at **WrenAI's thread view** screenshots (github.com/Canner/WrenAI README) and **Hex's Notebook Agent** announcement (hex.tech/blog/introducing-notebook-agent).

---

## Section 8 — What's NOT in this redesign

Explicitly out of scope:

- **Backend changes** — the ChatResponse contract is sufficient; no API change needed.
- **Framework migration** — stays Vue 3; alternate UI framework question separately parked.
- **New analyst features** — no new tools, no pivot/crosstab UI (that's audit #16, RFC required).
- **Theming overhaul** — design tokens stay; we use the existing palette better, not change it.
- **Performance work** — current bundle is fine for the redesign; no chunking changes.

These can come later if the redesign succeeds and creates appetite for follow-on work.

---

## Section 9 — Decision needed

Two top-level questions for you:

**A. Greenlight Phase 1 as a feasibility spike on a new branch?**
The first 3–5 days produce a working split-pane shell with the existing data flowing through. Low risk; reversible (delete the branch). Validates the pattern before committing to Phases 2–5.

**B. Or do another round of research / discussion first?**
If anything in this doc reads as too aggressive, too tame, or off-target, say so and I'll revise.

If A: I'll branch `redesign/split-pane-spike` off the current Wave 2A.5 tip and ship Phase 1 in ~3–5 commits with the same surgical pattern as Waves 1, 2A, 2A.5. Phase 2 and beyond are independent decisions you make after seeing Phase 1.

If B: tell me which decisions in Section 6 to firm up first, or which products / patterns you want me to dig deeper on.

---

## Appendix — Full citation list

### NL-to-data products
- Hex Notebook Agent — <https://hex.tech/blog/introducing-notebook-agent/>
- Hex changelog 2025-06-25 — <https://learn.hex.tech/changelog/2025-06-25>
- ThoughtSpot Spotter intro — <https://www.thoughtspot.com/blog/introducing-spotter-ai-analyst>
- Snowflake Cortex Analyst docs — <https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst>
- WrenAI GitHub — <https://github.com/Canner/WrenAI>
- Vanna.ai homepage (Vanna 2.0) — <https://vanna.ai/>
- Tableau Pulse + AI blog — <https://www.tableau.com/blog/tableau-pulse-and-tableau-ai>
- Power BI Q&A intro — <https://learn.microsoft.com/en-us/power-bi/natural-language/q-and-a-intro>
- Quadratic — <https://www.quadratichq.com/>
- Julius AI — <https://julius.ai/>
- Chat2DB UI overview — <https://chat2db.ai/resources/docs/start-guide/user-interface-overview>

### LLM chat + artifact patterns
- Claude Artifacts — <https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them>
- ChatGPT Canvas — <https://openai.com/index/introducing-canvas/>
- How Anthropic Built Artifacts — <https://newsletter.pragmaticengineer.com/p/how-anthropic-built-artifacts>
- Cursor 2.0 / Composer — <https://cursor.com/blog/2-0>
- v0 Docs — <https://v0.app/docs>
- Replit Agent — <https://docs.replit.com/replitai/agent>
- Continue.dev — <https://docs.continue.dev/ide-extensions/chat/quick-start>

### UX research / cognitive load
- NN/g — User Experience of Chatbots — <https://www.nngroup.com/articles/chatbots/>
- NN/g — Progressive Disclosure — <https://www.nngroup.com/articles/progressive-disclosure/>
- NN/g — 4 Principles to Reduce Cognitive Load — <https://www.nngroup.com/articles/4-principles-reduce-cognitive-load/>
- NN/g — Explainable AI in Chat Interfaces — <https://www.nngroup.com/articles/explainable-ai/>
- arXiv 2511.14718 — NLIDB user study — <https://arxiv.org/abs/2511.14718>
- Designative — The Conversation Trap (2026) — <https://www.designative.info/2026/03/19/the-conversation-trap-why-defaulting-to-chat-might-be-the-biggest-interaction-design-mistake-of-the-ai-era/>
- Stephen Few — Information Dashboard Design — <https://public.magendanz.com/Temp/Information%20Dashboard%20Design.pdf>
- Royal Society Open Science — Information overload in group communication — <https://royalsocietypublishing.org/doi/10.1098/rsos.191412>
