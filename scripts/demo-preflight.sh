#!/usr/bin/env bash
# ==========================================
# QueryfyAI — Phase 1 Demo Pre-flight
# ==========================================
# Runs the Python config validator, checks backend connectivity, and
# (optionally) clears stale caches so the demo starts from a clean state.
#
# Usage:
#   ./scripts/demo-preflight.sh                        # validate only
#   ./scripts/demo-preflight.sh --clear-cache          # validate + clear caches
#   ./scripts/demo-preflight.sh --backend-url URL      # custom backend URL
#   ./scripts/demo-preflight.sh --strict               # warnings fail
#   ./scripts/demo-preflight.sh --python /path/to/py   # force a specific Python
#   PREFLIGHT_PYTHON=/path/to/py ./scripts/demo-preflight.sh  # env-var alternative
#
# Python discovery:
#   The script walks candidate interpreters and picks the first one that
#   can "import app.core.config" (i.e. actually has pydantic-settings +
#   fastapi installed). Explicit --python / PREFLIGHT_PYTHON wins over
#   auto-discovery. Poetry users:
#     PREFLIGHT_PYTHON="$(cd backend && poetry env info -p)/bin/python"
#
# Intended to be run immediately before a live demo; catches env/config
# issues and stale-cache problems that have historically broken demos.
# See docs/demo-preflight-checklist.md for the manual verification matrix.
# ==========================================

set -euo pipefail

# -----------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
CLEAR_CACHE=false
STRICT=false
PYTHON_OVERRIDE="${PREFLIGHT_PYTHON:-}"

# Colors
RED=$'\033[31m'
YELLOW=$'\033[33m'
GREEN=$'\033[32m'
CYAN=$'\033[36m'
NC=$'\033[0m'

# -----------------------------------------------------------------
# Arg parsing
# -----------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --clear-cache)
            CLEAR_CACHE=true; shift ;;
        --backend-url)
            BACKEND_URL="$2"; shift 2 ;;
        --strict)
            STRICT=true; shift ;;
        --python)
            PYTHON_OVERRIDE="$2"; shift 2 ;;
        -h|--help)
            sed -n '3,28p' "$0" | sed 's/^# *//'
            exit 0 ;;
        *)
            echo "Unknown option: $1"; exit 2 ;;
    esac
done

# -----------------------------------------------------------------
# 1. Python config validator
# -----------------------------------------------------------------
echo "${CYAN}[1/4] Running config validator...${NC}"
VALIDATOR="$BACKEND_DIR/scripts/validate_demo_config.py"
if [[ ! -f "$VALIDATOR" ]]; then
    echo "${RED}  Validator not found at $VALIDATOR${NC}" >&2
    exit 2
fi

# Pick a Python interpreter that can actually import the backend
# package — not just any interpreter on PATH. A system python3 will
# satisfy the executable check but won't have pydantic-settings /
# fastapi / etc. installed, so the validator crashes on import. Walk
# candidates in order and pick the first one that can ``import
# app.core.config`` successfully.
PYTHON=""
CANDIDATES=()

# Explicit override: --python PATH or PREFLIGHT_PYTHON env var.
if [[ -n "$PYTHON_OVERRIDE" ]]; then
    CANDIDATES+=("$PYTHON_OVERRIDE")
fi

# Active venv (caller exported VIRTUAL_ENV — e.g. they ran ``source
# .venv/bin/activate`` before invoking the preflight).
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    CANDIDATES+=("$VIRTUAL_ENV/bin/python3" "$VIRTUAL_ENV/bin/python")
fi

# Common project-local venv layouts.
CANDIDATES+=(
    "$BACKEND_DIR/.venv/bin/python3"
    "$BACKEND_DIR/.venv/bin/python"
    "$BACKEND_DIR/venv/bin/python3"
    "$BACKEND_DIR/venv/bin/python"
    "$BACKEND_DIR/env/bin/python3"
    "$BACKEND_DIR/env/bin/python"
    "$PROJECT_DIR/.venv/bin/python3"
    "$PROJECT_DIR/.venv/bin/python"
)

# System fallback — versioned names first so we bypass pyenv shims that
# require a globally-set "python" alias (not the default).
for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
    resolved="$(command -v "$cmd" 2>/dev/null || true)"
    if [[ -n "$resolved" ]] && [[ -x "$resolved" ]]; then
        CANDIDATES+=("$resolved")
    fi
done

# Probe: does this Python have the backend package importable? A missing
# ``pydantic_settings`` is the common failure mode when the user has a
# venv for the backend at a non-standard path (poetry cache, pipx,
# ~/.virtualenvs, etc.) and the preflight fell through to a bare
# system python3.
WHY_SKIPPED=""
for candidate in "${CANDIDATES[@]}"; do
    if [[ ! -x "$candidate" ]]; then
        continue
    fi
    if (cd "$BACKEND_DIR" && "$candidate" -c "import app.core.config" >/dev/null 2>&1); then
        PYTHON="$candidate"
        break
    else
        # Remember the last one we rejected so the error message below
        # can be specific.
        WHY_SKIPPED="$candidate"
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "${RED}  No Python interpreter with backend dependencies found.${NC}" >&2
    if [[ -n "$WHY_SKIPPED" ]]; then
        echo "${RED}  Last rejected candidate: $WHY_SKIPPED${NC}" >&2
        echo "${RED}  (can't 'import app.core.config' — likely missing pydantic-settings / fastapi)${NC}" >&2
    fi
    echo "${RED}  Fixes:${NC}" >&2
    echo "${RED}    - Activate the backend venv: source backend/.venv/bin/activate${NC}" >&2
    echo "${RED}    - Or pass an explicit path: ./scripts/demo-preflight.sh --python /path/to/python${NC}" >&2
    echo "${RED}    - Or export: PREFLIGHT_PYTHON=/path/to/python ./scripts/demo-preflight.sh${NC}" >&2
    echo "${RED}    - Poetry users: PREFLIGHT_PYTHON=\"\$(cd backend && poetry env info -p)/bin/python\"${NC}" >&2
    exit 2
fi

VALIDATOR_ARGS=()
if [[ "$STRICT" == "true" ]]; then
    VALIDATOR_ARGS+=(--strict)
fi

# Bash "set -u" + an empty-array "${arr[@]}" expansion is an unbound-variable
# error on older bash (4.3-). Use the "+" conditional expansion so empty
# VALIDATOR_ARGS simply expands to nothing.
VALIDATOR_EXIT=0
(cd "$BACKEND_DIR" && "$PYTHON" scripts/validate_demo_config.py ${VALIDATOR_ARGS[@]+"${VALIDATOR_ARGS[@]}"}) \
    || VALIDATOR_EXIT=$?

# -----------------------------------------------------------------
# 2. Backend liveness (skip if validator already failed hard)
# -----------------------------------------------------------------
echo ""
echo "${CYAN}[2/4] Checking backend liveness at $BACKEND_URL ...${NC}"
if curl -sf -m 5 "$BACKEND_URL/health/live" > /dev/null 2>&1; then
    echo "  ${GREEN}OK${NC}    /health/live responds"
else
    echo "  ${YELLOW}WARN${NC}  backend not responding at $BACKEND_URL (demo needs it up)"
    VALIDATOR_EXIT=1
fi

# -----------------------------------------------------------------
# 3. Phase 1 diagnostic snapshot (fix flags + counters)
# -----------------------------------------------------------------
echo ""
echo "${CYAN}[3/4] Capturing Phase 1 diagnostic snapshot...${NC}"
if curl -sf -m 5 "$BACKEND_URL/health/diagnostic" 2>/dev/null; then
    echo ""
else
    echo "  ${YELLOW}WARN${NC}  /health/diagnostic not reachable (non-fatal; endpoint requires Day 0 scaffolding)"
fi

# -----------------------------------------------------------------
# 4. Optional cache clear
# -----------------------------------------------------------------
echo ""
echo "${CYAN}[4/4] Cache state${NC}"
if [[ "$CLEAR_CACHE" == "true" ]]; then
    echo "  Clearing all caches via POST /health/cache/invalidate?scope=all ..."
    if curl -sf -m 10 -X POST "$BACKEND_URL/health/cache/invalidate?scope=all" 2>/dev/null; then
        echo ""
        echo "  ${GREEN}OK${NC}    caches cleared"
    else
        echo "  ${YELLOW}WARN${NC}  cache invalidation endpoint did not respond"
    fi
else
    echo "  Skipped. Rerun with --clear-cache to wipe LLM/query/schema caches pre-demo."
fi

echo ""
if [[ "$VALIDATOR_EXIT" -eq 0 ]]; then
    echo "${GREEN}Pre-flight complete — demo can proceed.${NC}"
else
    echo "${RED}Pre-flight found blocking issues — address the ERRORs above before the demo.${NC}"
fi
exit "$VALIDATOR_EXIT"
