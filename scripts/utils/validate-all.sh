#!/bin/bash
# Run all validation checks (lint, type check, tests)
# Usage: ./scripts/utils/validate-all.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "================================================"
echo "Full Project Validation"
echo "================================================"
echo ""

FAILED=0

# Backend validation
echo "## Backend Validation"
echo ""

cd "$PROJECT_ROOT/backend"

echo "→ Ruff (linting)..."
if ruff check . 2>&1; then
    echo "  ✓ Passed"
else
    echo "  ✗ Failed"
    FAILED=1
fi
echo ""

echo "→ MyPy (type checking)..."
if mypy app/ 2>&1 | head -20; then
    echo "  ✓ Passed"
else
    echo "  ✗ Failed (showing first 20 errors)"
    FAILED=1
fi
echo ""

echo "→ Pytest (tests)..."
if pytest --tb=short -q 2>&1 | tail -20; then
    echo "  ✓ Passed"
else
    echo "  ✗ Failed (showing last 20 lines)"
    FAILED=1
fi
echo ""

# Frontend validation
cd "$PROJECT_ROOT/frontend"

echo "## Frontend Validation"
echo ""

echo "→ ESLint (linting)..."
if npm run lint 2>&1 | tail -20; then
    echo "  ✓ Passed"
else
    echo "  ✗ Failed (showing last 20 lines)"
    FAILED=1
fi
echo ""

echo "→ Build check..."
if npm run build 2>&1 | tail -20; then
    echo "  ✓ Passed"
else
    echo "  ✗ Failed (showing last 20 lines)"
    FAILED=1
fi
echo ""

# Summary
cd "$PROJECT_ROOT"
echo "================================================"
if [ $FAILED -eq 0 ]; then
    echo "✓ All validations passed!"
    exit 0
else
    echo "✗ Some validations failed"
    exit 1
fi
