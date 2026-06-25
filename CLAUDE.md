# CLAUDE.md

Project-specific instructions for Claude Code. Keep this file lean and universally applicable.

## Project Context (WHAT)

- **Type**: Monorepo — `frontend/` (Vue 3 + Vite) and `backend/` (FastAPI)
- **Purpose**: Natural language to SQL interface with visualization and ReAct agent
- **Stack**: Vue 3 Composition API, Pinia, Vite | Python 3.11+, FastAPI, async
- **Key Docs**: See `docs/` for architecture, API specs, and detailed guides

## Recent architecture decisions

Dated design docs future sessions should respect. Add a new file per major review; keep this list pruned to the last few months.

@docs/deep-audit-2026-05-09.md
@docs/analyst-mode-deep-audit-2026-04-22.md
@docs/agent-framework-review-2026-04-16.md

## Quick Commands (HOW)

```bash
# Frontend
cd frontend && npm run dev          # Dev server (:5173)
cd frontend && npm run build        # MUST run after changes
cd frontend && npm run lint         # Lint check

# Backend
cd backend && uvicorn app.main:app --reload --port 8000

# Docker
docker-compose up                   # Full stack
docker-compose -f docker-compose.production.yml up  # Production
```

## Utility Scripts

Fast bash utilities for code quality checks in `scripts/utils/`:

```bash
# Code Quality & Cleanup
./scripts/utils/find-unused-imports.sh [dir]  # Find unused Python imports
./scripts/utils/find-dead-code.sh [dir]       # Find unreferenced functions/classes
./scripts/utils/find-empty-files.sh           # Find empty or near-empty files

# Configuration
./scripts/utils/check-config-consistency.sh   # Check env file consistency

# Validation (runs all checks)
./scripts/utils/validate-all.sh               # Lint + type check + tests (both stacks)
```

**These are fast, standalone tools** that can be run directly or used by Claude skills.

## Maintenance Skills

Automated maintenance workflows via Claude Code skills:

```bash
/cleanup              # Interactive cleanup - scan and delete unused code/files
/config-audit         # Audit all config files for issues and inconsistencies
/pre-commit-validate  # Validate staged files before commit (use as git hook)
/weekly-cleanup       # Generate weekly cleanup report with recommendations
```

**Workflow:**
1. **Weekly:** Run `/weekly-cleanup` to generate a report
2. **Review:** Check findings and risk levels
3. **Cleanup:** Run `/cleanup` to interactively delete safe items
4. **Audit:** Run `/config-audit` after config changes

**Git hook integration:**
```bash
# Add pre-commit validation
ln -s ../../.claude/skills/pre-commit-validate/hook.sh .git/hooks/pre-commit
```

## Agent Workflow (IMPORTANT)

### Before Writing Code
1. **Read first** — NEVER propose changes to code you haven't read
2. **Search existing implementations** — Check if similar functionality exists before creating new
3. **Understand patterns** — Study how similar features are implemented in this codebase
4. **Reuse over create** — Extend/compose existing code rather than duplicate

### Before Committing
- [ ] `npm run build` passes without errors
- [ ] Feature tested manually in browser
- [ ] No console errors/warnings
- [ ] No commented-out code or console.logs

### Session State Management
**At the end of each session**, write progress to `.claude/session-state.md`:
- What was completed
- What remains to be done
- Any blockers or decisions needed
- Current branch and uncommitted changes

This ensures seamless resumption in the next session without context loss.

## File Operations

### Deletion Protocol
When deleting files or folders:
1. **List what will be deleted** — Show full paths and counts
2. **Wait for explicit confirmation** — Never delete without user approval
3. **Verify deletion** — Check files are gone after deletion
4. **Check for broken references** — Search for imports, configs, or references to deleted files

Example: Before deleting `old_module/`, check:
```bash
grep -r "from old_module" .
grep -r "old_module" *.yaml *.json *.toml
```

## Testing & Validation

### Post-Change Validation
After any codebase cleanup, refactor, or configuration change:

**Backend (Python):**
```bash
cd backend
ruff check .                    # Linting
mypy app/                       # Type checking
pytest                          # Run tests
```

**Frontend (Vue):**
```bash
cd frontend
npm run lint                    # ESLint
npm run build                   # Build check
# Run manual test in browser
```

**Never consider a task complete** until validation passes.

## Configuration Review

### Configuration Files Checklist
When reviewing YAML, JSON, `pyproject.toml`, `.env`, or docker-compose files:

- [ ] **Unused keys** — Remove deprecated or orphaned config
- [ ] **Deprecated options** — Check docs for updated syntax
- [ ] **Environment consistency** — `.env.example` matches `.env.production.example`
- [ ] **Missing required fields** — Compare against schema/docs
- [ ] **Sensitive data** — No secrets in version control
- [ ] **Comments** — Add explanations for non-obvious settings

Summarize findings in **checklist format** with file:line references.

## Git Conventions

- **No** "Co-Authored-By" tags
- Conventional commits: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`
- Scope by area: `feat(ui):`, `fix(api):`, `chore(deps):`
- Subject under 72 chars

## Code Style

### Frontend (Vue 3)
- **MUST** use `<script setup>` Composition API
- **MUST** use `storeToRefs()` when destructuring Pinia state/getters
- Icons: `lucide-vue-next` (UI), `@iconify/vue` (brands/databases)
- CSS: Scoped styles with `design-tokens.css` variables

### Backend (Python)
- All endpoints async
- Pydantic for validation
- Business logic in `app/services/`, keep routes thin

## Architecture Reference

```
frontend/src/
├── components/
│   ├── chat/           # ChatContainer, AIResponseCard, AgentTimeline
│   │   └── analyst/    # InsightCard, FollowUpSuggestions
│   ├── context-studio/ # Context/semantic layer management
│   ├── input/          # QueryBar, QueryInput, ConversationControls
│   ├── layout/         # App shell, header, drawers, NetworkBanner
│   ├── modals/         # DmlPreviewModal
│   ├── results/        # ResultsTable, ResultsExpander, JsonTreeModern
│   └── setup/          # Setup wizard
├── composables/        # useConversation, useQueryOptions, useStreamStatus, useToast
├── stores/             # activity, conversation, dataDictionary, session
└── utils/              # api, configService, errorCategories, networkStatus, resultAnalyzer, chartAnalyzer/
```

### Key Files
- `src/utils/api.js` — All API calls go through here
- `src/utils/configService.js` — Runtime config loaded from backend
- `src/stores/activity.js` — Query history, pinned items
- `src/stores/session.js` — Session and connection state
- `src/stores/conversation.js` — Chat conversation state

## Design Tokens

```css
/* Use these variables — don't hardcode values */
--color-primary, --bg-card, --bg-input, --bg-hover
--text-primary, --text-secondary, --text-muted
--space-xs (4px), --space-sm (8px), --space-md (16px), --space-lg (24px)
--radius-sm, --radius-md, --radius-lg
```

## DO NOT (Anti-patterns)

- **DON'T** create new files when editing existing ones suffices
- **DON'T** create utils/helpers for one-time operations
- **DON'T** add features, refactoring, or "improvements" beyond what's asked
- **DON'T** add error handling for scenarios that can't happen
- **DON'T** use !important in CSS
- **DON'T** leave backwards-compatibility shims for unused code
- **DON'T** create README/docs unless explicitly requested
- **DON'T** use top-level await in Vue setup (use `onMounted`)

## Common Pitfalls

| Issue | Solution |
|-------|----------|
| Pinia reactivity lost | Use `storeToRefs()` for state/getters |
| v-model on components | Use `modelValue` prop + `update:modelValue` emit |
| Large lists slow | Virtual scrolling for 100+ items |
| Watchers overused | Prefer computed properties |

## Terminology

- **ReAct Agent**: Tool-based reasoning agent in backend (`/api/v1/chat`)
- **Context Studio**: Schema/dictionary management UI (semantic layer)
- **Activity**: Query history + pinned items store
- **Provider**: Database or LLM service configuration

## When Unsure

1. Search codebase first — `Grep` for similar patterns
2. Read related files — understand existing implementation
3. Check `docs/` — architecture and API documentation
4. Ask for clarification — better than wrong assumptions

## Debugging Tips

- Frontend state issues → Check Vue DevTools, verify `storeToRefs()` usage
- API errors → Check Network tab, verify endpoint in `api.js`
- Build failures → Run `npm run lint`, check for TypeScript/import errors
- Styling issues → Inspect computed styles, check token usage
