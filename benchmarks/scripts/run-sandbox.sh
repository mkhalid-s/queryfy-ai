#!/usr/bin/env bash
# ============================================================================
# QueryfyAI Benchmark Sandbox Runner
# ============================================================================
# Orchestrates the full benchmark sandbox lifecycle:
#   1. Start database containers
#   2. Wait for health checks
#   3. Download benchmark data (if needed)
#   4. Load BIRD data into PostgreSQL/MySQL
#   5. Run benchmarks
#   6. Print results
#   7. Optionally tear down containers
#
# Usage:
#   bash benchmarks/scripts/run-sandbox.sh                  # Full run
#   bash benchmarks/scripts/run-sandbox.sh --config smoke   # Smoke test only
#   bash benchmarks/scripts/run-sandbox.sh --no-teardown    # Keep DBs running
#   bash benchmarks/scripts/run-sandbox.sh --skip-load      # Skip data loading
#
# Environment variables:
#   BENCHMARK_LLM_PROVIDER   — LLM provider (default: openai)
#   BENCHMARK_LLM_MODEL      — LLM model (default: gpt-4o-mini)
#   BENCHMARK_LLM_API_KEY_ENV — API key env var name (default: OPENAI_API_KEY)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/benchmarks/docker-compose.sandbox.yml"
DATA_DIR="${BENCHMARK_DATA_DIR:-benchmarks/data}"
CONFIG="${1:-sandbox}"
NO_TEARDOWN=false
SKIP_LOAD=false

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --no-teardown) NO_TEARDOWN=true ;;
        --skip-load)   SKIP_LOAD=true ;;
        --config)      ;; # handled positionally
        smoke|nightly|sandbox|cross-db) CONFIG="$arg" ;;
    esac
done

echo "============================================"
echo "  QueryfyAI Benchmark Sandbox Runner"
echo "============================================"
echo "  Config:    $CONFIG"
echo "  Data dir:  $DATA_DIR"
echo "  Provider:  ${BENCHMARK_LLM_PROVIDER:-openai}"
echo "  Model:     ${BENCHMARK_LLM_MODEL:-gpt-4o-mini}"
echo "============================================"
echo ""

# ------------------------------------------------------------------
# Step 1: Start database containers
# ------------------------------------------------------------------
echo "[1/6] Starting sandbox databases..."
docker compose -f "$COMPOSE_FILE" up -d
echo "  Containers started."

# ------------------------------------------------------------------
# Step 2: Wait for health checks
# ------------------------------------------------------------------
echo "[2/6] Waiting for databases to be healthy..."

wait_for_service() {
    local service="$1"
    local max_wait="${2:-60}"
    local elapsed=0

    while [ $elapsed -lt $max_wait ]; do
        status=$(docker compose -f "$COMPOSE_FILE" ps "$service" --format json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        data = data[0]
    print(data.get('Health', data.get('State', 'unknown')))
except: print('unknown')
" 2>/dev/null || echo "unknown")

        if echo "$status" | grep -qi "healthy"; then
            echo "  $service: healthy"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "  WARNING: $service did not become healthy within ${max_wait}s"
    return 1
}

wait_for_service "benchmark-postgres" 30 || true
wait_for_service "benchmark-mysql" 45 || true
wait_for_service "benchmark-mongodb" 30 || true
wait_for_service "benchmark-cassandra" 90 || true
wait_for_service "benchmark-dynamodb" 15 || true

echo ""

# ------------------------------------------------------------------
# Step 3: Download benchmark data (if needed)
# ------------------------------------------------------------------
echo "[3/6] Checking benchmark data..."
cd "$PROJECT_ROOT"

if [ ! -f "$DATA_DIR/bird-mini-dev/mini_dev_sqlite.json" ]; then
    echo "  Downloading BIRD Mini-Dev dataset..."
    python -m benchmarks download --dataset bird-mini-dev --data-dir "$DATA_DIR"
else
    echo "  BIRD Mini-Dev data already present."
fi

echo ""

# ------------------------------------------------------------------
# Step 4: Load BIRD data into PostgreSQL/MySQL
# ------------------------------------------------------------------
if [ "$SKIP_LOAD" = false ]; then
    echo "[4/6] Loading BIRD data into sandbox databases..."
    python benchmarks/scripts/load-bird-data.py --all --data-dir "$DATA_DIR" || {
        echo "  WARNING: Data loading had errors (benchmarks may still work with SQLite fallback)"
    }
else
    echo "[4/6] Skipping data load (--skip-load)."
fi

echo ""

# ------------------------------------------------------------------
# Step 5: Run benchmarks
# ------------------------------------------------------------------
echo "[5/6] Running benchmarks (config: $CONFIG)..."

CONFIG_FILE="benchmarks/configs/${CONFIG}.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "  ERROR: Config file not found: $CONFIG_FILE"
    echo "  Available configs:"
    ls -1 benchmarks/configs/*.yaml 2>/dev/null | sed 's/.*\//    /'
    exit 1
fi

# Export sandbox connection URLs for the config
export BENCHMARK_PG_URL="postgresql://benchmark:benchmark123@localhost:15432/benchmark_db"
export BENCHMARK_MYSQL_URL="mysql://benchmark:benchmark123@localhost:13306/benchmark_db"
export BENCHMARK_MONGO_URL="mongodb://benchmark:benchmark123@localhost:27018/"
export BENCHMARK_CASSANDRA_URL="cassandra://localhost:19042/banking_db"
export BENCHMARK_DYNAMODB_URL="dynamodb://fakeAccessKey:fakeSecretKey@localhost:18000"

python -m benchmarks run --config "$CONFIG_FILE" --output-format console

echo ""

# ------------------------------------------------------------------
# Step 6: Results summary
# ------------------------------------------------------------------
echo "[6/6] Benchmark run complete."
echo ""

# Find the most recent results directory
LATEST_RESULT=$(ls -td benchmarks/results/*/ 2>/dev/null | head -1)
if [ -n "$LATEST_RESULT" ]; then
    echo "  Results saved to: $LATEST_RESULT"
    if [ -f "${LATEST_RESULT}summary.json" ]; then
        echo ""
        python -m benchmarks report --run-dir "$LATEST_RESULT"
    fi
fi

# ------------------------------------------------------------------
# Teardown
# ------------------------------------------------------------------
if [ "$NO_TEARDOWN" = false ]; then
    echo ""
    echo "Tearing down sandbox containers..."
    docker compose -f "$COMPOSE_FILE" down -v
    echo "Done."
else
    echo ""
    echo "Sandbox containers left running (--no-teardown)."
    echo "To stop: docker compose -f benchmarks/docker-compose.sandbox.yml down -v"
fi
