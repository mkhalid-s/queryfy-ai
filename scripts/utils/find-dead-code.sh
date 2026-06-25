#!/bin/bash
# Find potentially dead code (unreferenced functions/classes)
# Usage: ./scripts/utils/find-dead-code.sh [directory]

set -e

DIR="${1:-backend/app}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "Scanning for dead code in: $DIR"
echo ""

# Find function definitions
echo "## Unreferenced Functions"
echo ""

grep -rn "^def " "$DIR" --include="*.py" | while IFS=: read -r file line func; do
    # Extract function name
    func_name=$(echo "$func" | sed 's/def \([a-zA-Z0-9_]*\).*/\1/')

    # Skip private functions (starting with _)
    [[ "$func_name" == _* ]] && continue

    # Skip __init__ and other magic methods
    [[ "$func_name" == __*__ ]] && continue

    # Count references (excluding the definition itself)
    refs=$(grep -r "\b$func_name\b" "$DIR" --include="*.py" | grep -v "^$file:$line:" | wc -l)

    if [ "$refs" -eq 0 ]; then
        echo "❌ $file:$line"
        echo "   Function: $func_name (0 references)"
    fi
done

echo ""
echo "## Unreferenced Classes"
echo ""

grep -rn "^class " "$DIR" --include="*.py" | while IFS=: read -r file line cls; do
    # Extract class name
    cls_name=$(echo "$cls" | sed 's/class \([a-zA-Z0-9_]*\).*/\1/')

    # Skip private classes
    [[ "$cls_name" == _* ]] && continue

    # Count references
    refs=$(grep -r "\b$cls_name\b" "$DIR" --include="*.py" | grep -v "^$file:$line:" | wc -l)

    if [ "$refs" -eq 0 ]; then
        echo "❌ $file:$line"
        echo "   Class: $cls_name (0 references)"
    fi
done

echo ""
echo "✓ Scan complete"
echo ""
echo "⚠️  Manual review recommended - some may be entry points or dynamic imports"
