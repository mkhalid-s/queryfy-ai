# Frontend — area-specific guidance

Loads on-demand when Claude works in `frontend/src/`. Captures area-specific patterns not covered in the root `CLAUDE.md`. Keep under 200 lines.

## Analyst-mode UX — degraded-narrator fallback

- `AIResponseCard.vue` renders a differentiated fallback card (`.insights-fallback`) when `insights=[]` AND the backend has shipped a `narrator_status` signal indicating degradation. Three cases handled today:
  - `skipped_no_llm_config` — warning tone, title "Statistical analysis only"
  - `ran_but_empty` — info tone, title "No notable patterns detected"
  - `ran_without_question_anchor` — info tone, title "Analysis without question context"
- Do NOT reintroduce the silent-blank-section behaviour for analyst mode. The fallback only fires when `isAnalystMode && narratorFallbackTitle`. Standard mode continues to hide the section entirely — unchanged.
- If adding a new narrator_status state, extend both `narratorFallbackTitle` and `narratorFallbackMessage` computeds in `AIResponseCard.vue` and add a matching `.fallback-<state>` CSS rule.

## Defensive-default pattern in card components

- `InsightCard.vue` uses `safeSeverity`, `safeTitle`, `safeDescription` computeds with fallbacks for every optional field. Rooted in the old "component crashed on `undefined.toUpperCase()` when a malformed LLM insight slipped through" regression — new card components MUST follow this pattern.

## Chart specs come through structured JSON, not text

- Chart data flows through `message.content.chart` (structured dict from backend `ChartSpec`) → `ContentTabs.vue` → chart component. Do NOT regex-parse chart blocks out of the assistant's text output. The `CHART_SPEC:` text-convention that once lived in `SYSTEM_PROMPT` has no parser and was removed in the 2026-04-22 prompt diet.

## Icon libraries

- `lucide-vue-next` for core UI icons (`Info`, `AlertCircle`, `ChevronRight`, `Bot`, `Sparkles`, `Copy`, `Check`, etc.). Add new icons to the existing `import` block in each component — do not create a second import line.
- `@iconify/vue` only for brand / database icons that lucide doesn't cover. Don't mix both libraries for the same purpose.

## Pinia + reactivity

- Use `storeToRefs()` when destructuring Pinia `state` or `getters` — otherwise reactivity is lost and computed bindings go stale. Actions don't need `storeToRefs` (they stay methods).
- `v-model` on custom components requires `modelValue` prop + `update:modelValue` emit, not `value` / `input`.

## Styling

- Design tokens are in `design-tokens.css`. Use variables (`--bg-card`, `--text-primary`, `--space-md`, `--radius-sm`, etc.) — never hardcode values.
- Never use `!important`.
- Scoped styles (`<style scoped>`) are the default. Global rules go in `design-tokens.css` or `style.css`.

## Validation

- `npm run lint` (ESLint) — keep warning count at or below current baseline (3 pre-existing warnings as of 2026-04-23).
- `npm run build` (Vite) — MUST pass before shipping. Catches script / import / template issues the lint misses.
