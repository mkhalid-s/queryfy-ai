#!/bin/bash
# Find unused Python imports across the codebase
# Usage: ./scripts/utils/find-unused-imports.sh [directory]

set -e

DIR="${1:-backend/app}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "Scanning for unused imports in: $DIR"
echo ""

# Find all Python files
find "$DIR" -name "*.py" -type f | while read -r file; do
    # Extract imports from the file
    imports=$(grep -E "^(from .+ import |import )" "$file" | sed 's/^from .* import //; s/^import //; s/ as .*//' | tr ',' '\n' | sed 's/^ *//; s/ *$//')

    if [ -z "$imports" ]; then
        continue
    fi

    # Check each import
    while IFS= read -r imp; do
        # Skip empty lines
        [ -z "$imp" ] && continue

        # Count usage (excluding the import line itself)
        count=$(grep -c "\b$imp\b" "$file" | grep -v "^import \|^from " || echo "0")

        if [ "$count" -le 1 ]; then
            echo "❌ $file"
            echo "   Unused: $imp"
        fi
    done <<< "$imports"
done | sort -u

echo ""
echo "✓ Scan complete"
echo ""
echo "To auto-fix with ruff:"
echo "  ruff check --select F401 --fix $DIR"
