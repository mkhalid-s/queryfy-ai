#!/bin/bash
# Check configuration consistency across environment files
# Usage: ./scripts/utils/check-config-consistency.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "Checking configuration consistency..."
echo ""

# Compare .env.example and .env.production.example
if [ -f ".env.example" ] && [ -f ".env.production.example" ]; then
    echo "## Comparing .env.example vs .env.production.example"
    echo ""

    # Extract keys from both files (ignore comments and empty lines)
    keys_example=$(grep -v "^#\|^$" .env.example | cut -d= -f1 | sort)
    keys_production=$(grep -v "^#\|^$" .env.production.example | cut -d= -f1 | sort)

    # Find keys only in .env.example
    echo "### Keys only in .env.example:"
    comm -23 <(echo "$keys_example") <(echo "$keys_production") || echo "(none)"
    echo ""

    # Find keys only in .env.production.example
    echo "### Keys only in .env.production.example:"
    comm -13 <(echo "$keys_example") <(echo "$keys_production") || echo "(none)"
    echo ""
fi

# Check for hardcoded secrets in docker-compose files
echo "## Scanning for potential secrets in docker-compose files"
echo ""

find . -name "docker-compose*.yml" -exec sh -c '
    secrets=$(grep -iE "password|secret|token|key" "$1" | grep -v "# " | grep -v "SECRET_KEY_BASE" || true)
    if [ -n "$secrets" ]; then
        echo "⚠️  $1:"
        echo "$secrets" | sed "s/^/   /"
        echo ""
    fi
' _ {} \;

# Check for unused docker-compose environment variables
echo "## Unused Environment Variables in docker-compose.yml"
echo ""

if [ -f "docker-compose.yml" ]; then
    grep -E "^\s+\- [A-Z_]+=" docker-compose.yml | sed 's/.*- //' | cut -d= -f1 | while read -r var; do
        # Check if variable is referenced in code
        refs=$(grep -r "\b$var\b" backend/ frontend/ --include="*.py" --include="*.js" --include="*.vue" 2>/dev/null | wc -l)
        if [ "$refs" -eq 0 ]; then
            echo "❌ $var (not found in code)"
        fi
    done
fi

echo ""
echo "✓ Scan complete"
