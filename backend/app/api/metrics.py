"""
QueryfyAI - Prometheus Metrics API

Uses prometheus_client for proper metrics with histograms, counters, and gauges.
Provides both Prometheus-format /metrics and detailed JSON /metrics/detailed endpoints.
"""

import os
import threading
import time
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Response

from app.core.logging_config import get_logger
from app.core.version import __version__ as APP_VERSION
from app.models.schemas import (
    AgentMetrics,
    DatabaseMetrics,
    DetailedMetricsResponse,
    LLMMetrics,
    RequestMetrics,
    SessionMetrics,
)

logger = get_logger(__name__)

router = APIRouter()

# ============================================================================
# Prometheus Metrics Definitions
# ============================================================================

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
        multiprocess,
    )

    # Detect multi-process mode (F20). Set in Dockerfile.production via
    # `prometheus_multiproc_dir`. Under gunicorn with N workers, each
    # worker has its own in-process REGISTRY; without MultiProcessCollector
    # at scrape time, Prometheus sees whichever worker happened to handle
    # the /metrics request — counters under-report by ~(N-1)/N and gauges
    # flutter.  When the dir is set, scraping reads the shared mmap files
    # and aggregates per `multiprocess_mode` on each Gauge.
    _MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR") or os.environ.get(
        "prometheus_multiproc_dir"
    )
    PROMETHEUS_MULTIPROC = bool(_MULTIPROC_DIR)

    # Application info
    app_info = Info("queryfyai", "QueryfyAI application information")
    app_info.info({"version": APP_VERSION})

    # Uptime tracking
    _start_time = time.time()

    # Request counters
    http_requests_total = Counter(
        "queryfyai_http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status"],
    )
    http_request_duration = Histogram(
        "queryfyai_http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["method", "endpoint"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )

    # LLM metrics
    llm_requests_total = Counter(
        "queryfyai_llm_requests_total",
        "Total LLM requests",
        ["provider", "model", "status"],
    )
    llm_request_duration = Histogram(
        "queryfyai_llm_request_duration_seconds",
        "LLM request latency in seconds",
        ["provider", "model"],
        buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
    )
    llm_tokens_total = Counter(
        "queryfyai_llm_tokens_total",
        "Total LLM tokens used",
        ["provider", "model", "type"],  # type label: "input" or "output"
    )
    llm_cache_operations = Counter(
        "queryfyai_llm_cache_operations_total",
        "LLM cache operations",
        ["result"],  # result label: "hit" or "miss"
    )
    llm_cost_total = Counter(
        "queryfyai_llm_cost_usd_total", "Total LLM cost in USD", ["provider", "model"]
    )

    # Database query metrics
    db_queries_total = Counter(
        "queryfyai_db_queries_total", "Total database queries", ["db_type", "status"]
    )
    db_query_duration = Histogram(
        "queryfyai_db_query_duration_seconds",
        "Database query latency in seconds",
        ["db_type"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
    )
    db_cache_operations = Counter(
        "queryfyai_db_cache_operations_total",
        "Database query cache operations",
        ["result"],  # hit/miss
    )
    db_rows_returned = Histogram(
        "queryfyai_db_rows_returned",
        "Number of rows returned by database queries",
        ["db_type"],
        buckets=[1, 10, 50, 100, 500, 1000, 5000, 10000],
    )

    # Agent metrics
    agent_runs_total = Counter(
        "queryfyai_agent_runs_total",
        "Total SQL agent runs",
        ["status"],  # success/failure
    )
    agent_run_duration = Histogram(
        "queryfyai_agent_run_duration_seconds",
        "SQL agent execution time in seconds",
        buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
    )
    agent_retries_total = Counter(
        "queryfyai_agent_retries_total", "Total SQL agent retries"
    )
    agent_attempts_histogram = Histogram(
        "queryfyai_agent_attempts",
        "Number of attempts per agent run",
        buckets=[1, 2, 3, 4, 5],
    )

    # Session metrics. `livemax` semantics under multiproc: each worker
    # pushes the Redis-truth total on every session lifecycle event, so
    # all live workers eventually converge to the same number; taking
    # the max across alive workers tolerates the small write-skew window.
    # See F20 in docs/PLAN-TRACKER.md.
    if PROMETHEUS_MULTIPROC:
        active_sessions = Gauge(
            "queryfyai_active_sessions",
            "Number of active sessions",
            multiprocess_mode="livemax",
        )
    else:
        active_sessions = Gauge(
            "queryfyai_active_sessions",
            "Number of active sessions",
        )

    # MCP endpoint enable signal. Operators read this on the dashboard
    # or in the staging-soak alert to confirm the carve-out gate state.
    # Set from settings at module load; if MCP_ENDPOINT_ENABLED is
    # flipped at runtime via SIGHUP-restart, the gauge follows on the
    # next worker boot. Used by the MCPEndpointEnabledNoTraffic alert.
    #
    # `livemax` semantics under multiproc: every worker writes the same
    # boolean (read from the same settings instance). Without this mode
    # the gauge defaults to per-pid series under multiproc, and the
    # alert query `queryfyai_mcp_enabled == 1` would not match the
    # aggregated scrape result (caught by 3-reviewer convergence on
    # commit 35bed58 — see F48 in PLAN-TRACKER.md).
    if PROMETHEUS_MULTIPROC:
        mcp_enabled = Gauge(
            "queryfyai_mcp_enabled",
            "1 when MCP endpoint is enabled (MCP_ENDPOINT_ENABLED=true), else 0",
            multiprocess_mode="livemax",
        )
    else:
        mcp_enabled = Gauge(
            "queryfyai_mcp_enabled",
            "1 when MCP endpoint is enabled (MCP_ENDPOINT_ENABLED=true), else 0",
        )

    queries_generated = Counter(
        "queryfyai_queries_generated_total", "Total SQL queries generated"
    )

    # Result-cache operation counter. Tracks cache hit/miss/error across
    # both the storage layer (result_cache.get/store/aget/astore) and the
    # LLM-facing inspection tools (get_cached_rows, inspect_cached_result).
    # operation: "get" | "store" | "slice" | "inspect"
    # result:    "hit" | "miss" | "error"
    result_cache_operations_total = Counter(
        "queryfyai_result_cache_operations_total",
        "Result-cache operations by operation type and outcome",
        ["operation", "result"],
    )

    # Retrieval fallback counter (Architect P1 — Pass 3 closeout).
    # Fires when `_search_relevant_columns` returns [] and the query-aware
    # `get_column_context` path falls back to the legacy "dump every
    # column" behaviour. Without this counter, three different failure
    # modes look identical: (a) ChromaDB/Qdrant unreachable, (b) the
    # collection has no entries for this connection_hash yet, (c) the
    # semantic query genuinely produced no relevant matches. Distinguishing
    # them is load-bearing for retrieval debugging once the B2 flag flips.
    retrieval_fallback_total = Counter(
        "queryfyai_retrieval_fallback_total",
        "Retrieval fallbacks from query-aware to legacy dump path",
        ["reason"],  # "vector_db_unavailable" | "exception" | "no_results"
    )

    # Circuit breaker metrics. Under multiproc: `livemax` is correct here
    # too — open (1) or half-open (2) dominates closed (0) on the dashboard,
    # which is the failure-mode we want surfaced (a single worker tripping
    # the breaker should light up the panel).
    if PROMETHEUS_MULTIPROC:
        circuit_breaker_state = Gauge(
            "queryfyai_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=open, 2=half-open)",
            ["provider"],
            multiprocess_mode="livemax",
        )
    else:
        circuit_breaker_state = Gauge(
            "queryfyai_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=open, 2=half-open)",
            ["provider"],
        )

    # Phase 1 reliability fix effectiveness counters.
    # Each increments when the corresponding fix catches a bug that would have
    # been silently masked before. See docs/architecture-audit-2026-04-16.md.
    fix_event_total = Counter(
        "queryfyai_fix_event_total",
        "Phase 1 reliability fix events (bug caught by a remediation fix)",
        ["fix_name"],  # e.g. "json_error_detection", "success_field_check"
    )

    PROMETHEUS_AVAILABLE = True

except ImportError:
    logger.warning("prometheus_client not installed, falling back to basic metrics")
    PROMETHEUS_AVAILABLE = False
    _start_time = time.time()


# ============================================================================
# Backward-Compatible Metrics Storage (for legacy code)
# ============================================================================

_legacy_metrics = {
    "requests_total": 0,
    "requests_success": 0,
    "requests_error": 0,
    "queries_generated": 0,
    "queries_executed": 0,
    "active_sessions": 0,
    "llm_requests_total": 0,
    "llm_cache_hits": 0,
    "llm_cache_misses": 0,
    "llm_errors": 0,
    "llm_latency_sum": 0.0,
    "llm_latency_count": 0,
    "query_cache_hits": 0,
    "query_cache_misses": 0,
    "agent_runs_total": 0,
    "agent_retries_total": 0,
    "agent_success": 0,
    "agent_failures": 0,
}

# Phase 1 fix-effectiveness counters (separate dict keeps the fix names together
# and avoids namespace pollution in the legacy dict)
_fix_events: Dict[str, int] = {
    "json_error_detection": 0,   # Day 1a fix caught a JSON-encoded success=false
    "success_field_check": 0,    # Day 1b fix caught success=false in tool_node success path
    "column_name_field": 0,      # Day 2a fix provided column_name for dedup
    "insight_deduplication": 0,  # Day 2b fix dropped a duplicate insight
    "smart_id_exclusion": 0,     # Day 2c fix excluded an ID column from analysis
    "date_based_trends": 0,      # Day 2c fix used real dates instead of row index
    "data_lake_timeout": 0,      # Day 4 fix applied longer timeout for data-lake DB
    # Phase 2 fix-effectiveness counters.
    "two_counter_circuit_breaker": 0,       # Day 1: breaker tripped on SQL failures specifically
    "checkpoint_resume_safe_copy": 0,       # Day 2: resumed via deep-copy helper (no in-place mutation)
    "tool_task_cancelled_on_timeout": 0,    # Day 2: explicit cancel propagated to tool coroutine
    "distributed_lock_fail_loud": 0,        # Day 3: refused local fallback in production
    "background_lock_extension_failure": 0, # Day 3: extender task exited on extend-returned-False
    "pool_preflight_discarded": 0,          # Day 3: discarded a dead pool connection
    "shutdown_drain_timeout": 0,            # Day 4: drain hit the timeout with requests in flight
}
_metrics_lock = threading.Lock()


def increment_metric(name: str, value: int = 1):
    """Increment a metric counter (backward compatible)"""
    with _metrics_lock:
        if name in _legacy_metrics:
            _legacy_metrics[name] += value


def set_metric(name: str, value: int):
    """Set a metric gauge value (backward compatible)"""
    with _metrics_lock:
        _legacy_metrics[name] = value


def add_metric(name: str, value: float):
    """Add to a metric (for latency sums, etc.) (backward compatible)"""
    with _metrics_lock:
        if name in _legacy_metrics:
            _legacy_metrics[name] += value


def record_llm_latency(latency_ms: float):
    """Record LLM request latency (backward compatible)"""
    with _metrics_lock:
        _legacy_metrics["llm_latency_sum"] += latency_ms
        _legacy_metrics["llm_latency_count"] += 1


def get_metrics_snapshot() -> Dict[str, Any]:
    """Get a snapshot of all metrics (backward compatible)"""
    with _metrics_lock:
        return dict(_legacy_metrics)


# ============================================================================
# New Prometheus-Based Metrics Functions
# ============================================================================


def record_http_request(method: str, endpoint: str, status: int, duration: float):
    """Record an HTTP request with Prometheus metrics."""
    if PROMETHEUS_AVAILABLE:
        http_requests_total.labels(
            method=method, endpoint=endpoint, status=str(status)
        ).inc()
        http_request_duration.labels(method=method, endpoint=endpoint).observe(duration)

    # Also update legacy metrics
    with _metrics_lock:
        _legacy_metrics["requests_total"] += 1
        if 200 <= status < 400:
            _legacy_metrics["requests_success"] += 1
        else:
            _legacy_metrics["requests_error"] += 1


def record_llm_request(
    provider: str,
    model: str,
    status: str,
    duration_seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_hit: bool = False,
    cost_usd: float = 0.0,
):
    """Record an LLM request with Prometheus metrics."""
    if PROMETHEUS_AVAILABLE:
        llm_requests_total.labels(provider=provider, model=model, status=status).inc()
        llm_request_duration.labels(provider=provider, model=model).observe(
            duration_seconds
        )

        if input_tokens > 0:
            llm_tokens_total.labels(provider=provider, model=model, type="input").inc(
                input_tokens
            )

        if output_tokens > 0:
            llm_tokens_total.labels(provider=provider, model=model, type="output").inc(
                output_tokens
            )

        llm_cache_operations.labels(result="hit" if cache_hit else "miss").inc()

        # Record cost if provided
        if cost_usd > 0:
            llm_cost_total.labels(provider=provider, model=model).inc(cost_usd)

    # Also update legacy metrics
    with _metrics_lock:
        _legacy_metrics["llm_requests_total"] += 1
        _legacy_metrics["llm_latency_sum"] += duration_seconds * 1000
        _legacy_metrics["llm_latency_count"] += 1
        if cache_hit:
            _legacy_metrics["llm_cache_hits"] += 1
        else:
            _legacy_metrics["llm_cache_misses"] += 1
        if status == "error":
            _legacy_metrics["llm_errors"] += 1


def record_db_query(
    db_type: str,
    status: str,
    duration_seconds: float,
    rows_returned: int = 0,
    cache_hit: bool = False,
):
    """Record a database query with Prometheus metrics."""
    if PROMETHEUS_AVAILABLE:
        db_queries_total.labels(db_type=db_type, status=status).inc()
        db_query_duration.labels(db_type=db_type).observe(duration_seconds)

        if rows_returned > 0:
            db_rows_returned.labels(db_type=db_type).observe(rows_returned)

        db_cache_operations.labels(result="hit" if cache_hit else "miss").inc()

    # Also update legacy metrics
    with _metrics_lock:
        _legacy_metrics["queries_executed"] += 1
        if cache_hit:
            _legacy_metrics["query_cache_hits"] += 1
        else:
            _legacy_metrics["query_cache_misses"] += 1


def record_agent_run(status: str, duration_seconds: float, attempts: int = 1):
    """Record an agent run with Prometheus metrics."""
    if PROMETHEUS_AVAILABLE:
        agent_runs_total.labels(status=status).inc()
        agent_run_duration.observe(duration_seconds)
        agent_attempts_histogram.observe(attempts)

        if attempts > 1:
            agent_retries_total.inc(attempts - 1)

    # Also update legacy metrics
    with _metrics_lock:
        _legacy_metrics["agent_runs_total"] += 1
        if attempts > 1:
            _legacy_metrics["agent_retries_total"] += attempts - 1
        if status == "success":
            _legacy_metrics["agent_success"] += 1
        else:
            _legacy_metrics["agent_failures"] += 1


def record_query_generated():
    """Record a generated SQL query."""
    if PROMETHEUS_AVAILABLE:
        queries_generated.inc()

    with _metrics_lock:
        _legacy_metrics["queries_generated"] += 1


def update_active_sessions(count: int):
    """Update the active sessions gauge."""
    if PROMETHEUS_AVAILABLE:
        active_sessions.set(count)

    with _metrics_lock:
        _legacy_metrics["active_sessions"] = count


def record_cache_operation(operation: str, result: str) -> None:
    """
    Increment ``queryfyai_result_cache_operations_total{operation, result}``.

    operation: one of ``get`` | ``store`` | ``slice`` | ``inspect``
    result:    one of ``hit`` | ``miss`` | ``error``

    Best-effort: never raises into the caller. The cache must keep
    working even if prometheus_client is misconfigured.
    """
    if not PROMETHEUS_AVAILABLE:
        return
    try:
        result_cache_operations_total.labels(operation=operation, result=result).inc()
    except Exception:  # pragma: no cover — metrics is best-effort
        pass


def update_circuit_breaker_state(provider: str, state: int):
    """Update circuit breaker state (0=closed, 1=open, 2=half-open)."""
    if PROMETHEUS_AVAILABLE:
        circuit_breaker_state.labels(provider=provider).set(state)


# ============================================================================
# Phase 1 Fix-Effectiveness Metrics
# ============================================================================

# Valid fix names. Calls with unknown names are rejected to catch typos early.
_KNOWN_FIX_NAMES = frozenset(_fix_events.keys())


def record_fix_event(fix_name: str) -> None:
    """
    Record that a Phase 1 reliability fix caught a bug.

    Each call represents one instance where the fix prevented a silently-masked
    failure. Used by `/health/diagnostic` to prove fixes are active in
    production.

    Args:
        fix_name: one of the names in _fix_events (e.g. "json_error_detection").
                  Unknown names are logged as a warning but do not raise, so a
                  typo never takes down the request path.
    """
    if fix_name not in _KNOWN_FIX_NAMES:
        logger.warning("record_fix_event: unknown fix_name %r", fix_name)
        return

    if PROMETHEUS_AVAILABLE:
        fix_event_total.labels(fix_name=fix_name).inc()

    with _metrics_lock:
        _fix_events[fix_name] += 1


def get_fix_events_snapshot() -> Dict[str, int]:
    """Return a copy of current fix-event counts for the diagnostic endpoint."""
    with _metrics_lock:
        return dict(_fix_events)


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/metrics")
async def get_metrics():
    """
    Prometheus-compatible metrics endpoint.
    Returns metrics in Prometheus text format using prometheus_client.

    Under multi-process mode (gunicorn N>1 workers; F20): collect across
    all workers via MultiProcessCollector mmap-file aggregation. In
    single-process mode (uvicorn / dev) read from the in-process
    REGISTRY directly.
    """
    if PROMETHEUS_AVAILABLE:
        # Add uptime metric dynamically
        time.time() - _start_time

        if PROMETHEUS_MULTIPROC:
            # Fresh registry per scrape; MultiProcessCollector reads
            # the mmap files written by every worker.
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            return Response(
                content=generate_latest(registry),
                media_type=CONTENT_TYPE_LATEST,
            )

        return Response(
            content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST
        )
    else:
        # Fallback to manual generation if prometheus_client not available
        return _generate_legacy_metrics()


def _generate_legacy_metrics():
    """Generate metrics in Prometheus format without prometheus_client."""
    uptime = time.time() - _start_time

    output = []

    # Application info
    output.append("# HELP queryfyai_info Application information")
    output.append("# TYPE queryfyai_info gauge")
    output.append(f'queryfyai_info{{version="{APP_VERSION}"}} 1')

    # Uptime
    output.append("# HELP queryfyai_uptime_seconds Application uptime in seconds")
    output.append("# TYPE queryfyai_uptime_seconds counter")
    output.append(f"queryfyai_uptime_seconds {uptime:.2f}")

    with _metrics_lock:
        metrics = dict(_legacy_metrics)

    # Request counters
    output.append("# HELP queryfyai_requests_total Total number of requests")
    output.append("# TYPE queryfyai_requests_total counter")
    output.append(f'queryfyai_requests_total {metrics["requests_total"]}')

    output.append("# HELP queryfyai_requests_success Total successful requests")
    output.append("# TYPE queryfyai_requests_success counter")
    output.append(f'queryfyai_requests_success {metrics["requests_success"]}')

    output.append("# HELP queryfyai_requests_error Total error requests")
    output.append("# TYPE queryfyai_requests_error counter")
    output.append(f'queryfyai_requests_error {metrics["requests_error"]}')

    # LLM metrics
    output.append("# HELP queryfyai_llm_requests_total Total LLM requests")
    output.append("# TYPE queryfyai_llm_requests_total counter")
    output.append(f'queryfyai_llm_requests_total {metrics["llm_requests_total"]}')

    avg_latency = 0.0
    if metrics["llm_latency_count"] > 0:
        avg_latency = metrics["llm_latency_sum"] / metrics["llm_latency_count"]
    output.append(
        "# HELP queryfyai_llm_latency_avg_ms Average LLM latency in milliseconds"
    )
    output.append("# TYPE queryfyai_llm_latency_avg_ms gauge")
    output.append(f"queryfyai_llm_latency_avg_ms {avg_latency:.2f}")

    # Agent metrics
    output.append("# HELP queryfyai_agent_runs_total Total SQL agent runs")
    output.append("# TYPE queryfyai_agent_runs_total counter")
    output.append(f'queryfyai_agent_runs_total {metrics["agent_runs_total"]}')

    output.append("# HELP queryfyai_agent_success Successful agent runs")
    output.append("# TYPE queryfyai_agent_success counter")
    output.append(f'queryfyai_agent_success {metrics["agent_success"]}')

    output.append("# HELP queryfyai_agent_failures Failed agent runs")
    output.append("# TYPE queryfyai_agent_failures counter")
    output.append(f'queryfyai_agent_failures {metrics["agent_failures"]}')

    return Response(
        content="\n".join(output) + "\n", media_type="text/plain; charset=utf-8"
    )


@router.get("/metrics/detailed", response_model=DetailedMetricsResponse)
async def detailed_metrics() -> DetailedMetricsResponse:
    """
    Detailed metrics endpoint for monitoring dashboards.
    Returns structured JSON with comprehensive metrics.
    """
    uptime = time.time() - _start_time

    with _metrics_lock:
        metrics = dict(_legacy_metrics)

    # Calculate derived metrics
    llm_cache_total = metrics["llm_cache_hits"] + metrics["llm_cache_misses"]
    llm_cache_hit_rate = (
        (metrics["llm_cache_hits"] / llm_cache_total * 100)
        if llm_cache_total > 0
        else 0.0
    )

    query_cache_total = metrics["query_cache_hits"] + metrics["query_cache_misses"]
    query_cache_hit_rate = (
        (metrics["query_cache_hits"] / query_cache_total * 100)
        if query_cache_total > 0
        else 0.0
    )

    llm_avg_latency = (
        metrics["llm_latency_sum"] / metrics["llm_latency_count"]
        if metrics["llm_latency_count"] > 0
        else 0.0
    )

    agent_total = metrics["agent_success"] + metrics["agent_failures"]
    agent_success_rate = (
        (metrics["agent_success"] / agent_total * 100) if agent_total > 0 else 0.0
    )

    agent_avg_attempts = 1.0
    if metrics["agent_runs_total"] > 0:
        agent_avg_attempts = 1.0 + (
            metrics["agent_retries_total"] / metrics["agent_runs_total"]
        )

    # Get pool stats if available
    pool_stats = {}
    try:
        from app.services.connection_pool_manager import pool_manager

        pool_stats = pool_manager.get_pool_stats()
    except ImportError:
        logger.debug("Connection pool manager not available for metrics")

    # Get session count
    session_count = metrics["active_sessions"]
    try:
        from app.services.session_store import session_store

        session_count = len(session_store.list_sessions(limit=1000))
    except ImportError:
        logger.debug("Session store not available for metrics")

    return DetailedMetricsResponse(
        timestamp=datetime.now().isoformat(),
        uptime_seconds=round(uptime, 2),
        requests=RequestMetrics(
            total=int(metrics["requests_total"]),
            success=int(metrics["requests_success"]),
            errors=int(metrics["requests_error"]),
            success_rate=(
                (metrics["requests_success"] / metrics["requests_total"] * 100)
                if metrics["requests_total"] > 0
                else 100.0
            ),
        ),
        llm=LLMMetrics(
            total_requests=int(metrics["llm_requests_total"]),
            cache_hits=int(metrics["llm_cache_hits"]),
            cache_misses=int(metrics["llm_cache_misses"]),
            cache_hit_rate=round(llm_cache_hit_rate, 2),
            errors=int(metrics["llm_errors"]),
            avg_latency_ms=round(llm_avg_latency, 2),
        ),
        database=DatabaseMetrics(
            queries_executed=int(metrics["queries_executed"]),
            cache_hits=int(metrics["query_cache_hits"]),
            cache_misses=int(metrics["query_cache_misses"]),
            cache_hit_rate=round(query_cache_hit_rate, 2),
            pool_stats=pool_stats,
        ),
        agent=AgentMetrics(
            total_runs=int(metrics["agent_runs_total"]),
            total_retries=int(metrics["agent_retries_total"]),
            successes=int(metrics["agent_success"]),
            failures=int(metrics["agent_failures"]),
            success_rate=round(agent_success_rate, 2),
            avg_attempts=round(agent_avg_attempts, 2),
        ),
        sessions=SessionMetrics(
            active=int(session_count),
            queries_generated=int(metrics["queries_generated"]),
        ),
    )
