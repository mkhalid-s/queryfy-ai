#!/usr/bin/env bash
#
# Backend test runner with venv self-heal.
#
# Audit risk R1 (Wave 2A.5 mitigation): the bundled venv at
# backend/venv/ may be a broken symlink in dev containers (it
# points at a host-local pyenv path that doesn't exist in the
# container's filesystem). Without this script every developer
# has to remember to rebuild the venv manually before every
# pytest run, and CI gets brittle. This script detects the
# broken state and rebuilds in place.
#
# Usage:
#   bash backend/scripts/run-tests.sh                       # all tests
#   bash backend/scripts/run-tests.sh tests/unit            # narrow
#   bash backend/scripts/run-tests.sh -k some_pattern -v    # pytest pass-through
#   bash backend/scripts/run-tests.sh --skip-rebuild        # use existing venv
#
# Exit codes mirror pytest's (0 pass, non-zero on failure).
set -euo pipefail

cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"/.. && pwd)"

SKIP_REBUILD=0
if [[ "${1:-}" == "--skip-rebuild" ]]; then
    SKIP_REBUILD=1
    shift
fi

needs_rebuild() {
    [[ ! -x venv/bin/python ]] && return 0
    venv/bin/python --version >/dev/null 2>&1 || return 0
    venv/bin/python -c "import pytest" >/dev/null 2>&1 || return 0
    return 1
}

build_venv() {
    rm -rf venv
    # Prefer uv (modern, fast, no ensurepip dependency); fall back to
    # python3 -m venv (stdlib but needs python3-venv apt package on
    # Debian-family containers).
    if command -v uv >/dev/null 2>&1; then
        echo ">> using uv to build venv"
        uv venv venv --quiet
        uv pip install --python venv/bin/python \
            -r requirements.txt -r requirements-dev.txt --quiet
    elif python3 -c "import ensurepip" >/dev/null 2>&1; then
        echo ">> using python3 -m venv"
        python3 -m venv venv
        venv/bin/pip install --upgrade pip --quiet
        venv/bin/pip install -r requirements.txt -r requirements-dev.txt --quiet
    else
        cat <<'ERR' >&2
ERROR: No working venv builder found.
  - 'uv' is missing — install via: curl -LsSf https://astral.sh/uv/install.sh | sh
  - 'python3-venv' is missing — install via: apt install python3.13-venv

If you cannot install either, run pytest on a host that has them.
ERR
        exit 1
    fi
    echo ">> venv built."
}

if [[ $SKIP_REBUILD -eq 0 ]] && needs_rebuild; then
    echo ">> venv broken or missing — rebuilding..."
    build_venv
fi

exec venv/bin/pytest "$@"
