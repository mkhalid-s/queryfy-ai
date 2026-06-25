#!/bin/bash
# Find empty or near-empty files
# Usage: ./scripts/utils/find-empty-files.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "Scanning for empty/near-empty files..."
echo ""

echo "## Completely Empty Files"
find . -type f -empty \
    ! -path "./node_modules/*" \
    ! -path "./.git/*" \
    ! -path "./venv/*" \
    ! -path "./.venv/*" \
    ! -path "./dist/*" \
    ! -path "./build/*"

echo ""
echo "## Empty __init__.py Files"
find . -name "__init__.py" -type f \
    ! -path "./node_modules/*" \
    ! -path "./.git/*" \
    ! -path "./venv/*" \
    ! -path "./.venv/*" \
    -exec sh -c 'grep -v "^#\|^$" "$1" > /dev/null || echo "$1"' _ {} \;

echo ""
echo "## Files with Only Comments"
find . -type f \( -name "*.py" -o -name "*.js" -o -name "*.vue" \) \
    ! -path "./node_modules/*" \
    ! -path "./.git/*" \
    ! -path "./venv/*" \
    ! -path "./.venv/*" \
    ! -path "./dist/*" \
    -exec sh -c '
        content=$(grep -v "^#\|^//\|^\s*$" "$1" | wc -l)
        if [ "$content" -eq 0 ]; then
            echo "$1"
        fi
    ' _ {} \;

echo ""
echo "✓ Scan complete"
