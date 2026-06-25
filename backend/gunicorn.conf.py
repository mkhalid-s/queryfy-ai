"""
QueryfyAI - Gunicorn Configuration

Production configuration for multi-worker deployment.
Supports horizontal scaling with multiple worker processes.
"""

import logging
import multiprocessing
import os

# Configure logger for gunicorn hooks
logger = logging.getLogger("gunicorn.error")

# ============================================================================
# WORKERS
# ============================================================================

# Number of worker processes
# Formula: (2 * CPU cores) + 1 for optimal performance
# Can be overridden with GUNICORN_WORKERS env var
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))

# Worker class - use Uvicorn's worker for async support
worker_class = "uvicorn.workers.UvicornWorker"

# Threads per worker (for sync operations)
threads = int(os.getenv("GUNICORN_THREADS", 1))

# ============================================================================
# TIMEOUTS
# ============================================================================

# Request timeout (seconds) - allow long-running queries
timeout = int(os.getenv("GUNICORN_TIMEOUT", 300))

# Graceful shutdown timeout
graceful_timeout = 30

# Keep-alive connections timeout
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", 5))

# ============================================================================
# SERVER
# ============================================================================

# Bind address
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# Maximum requests before worker restart (prevents memory leaks)
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = 100

# Backlog for pending connections
backlog = 2048

# ============================================================================
# LOGGING
# ============================================================================

# Access log
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")  # stdout

# Error log
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")  # stderr

# Log level
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# Log format
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# ============================================================================
# PROCESS NAMING
# ============================================================================

# Process name
proc_name = "queryfyai"

# ============================================================================
# SERVER MECHANICS
# ============================================================================

# Preload app for shared memory (faster startup, shared connections)
preload_app = True

# Daemon mode (False for Docker)
daemon = False

# User/Group (for security)
# user = "www-data"
# group = "www-data"

# ============================================================================
# HOOKS
# ============================================================================


def on_starting(server):
    """Called just before the master process is initialized."""
    logger.info(f"QueryfyAI starting with {workers} workers")
    # Clear stale prometheus_client multiprocess files from any
    # previous run before workers fork. The mmap files are keyed by
    # per-process gauge/counter state — stale files from a previous
    # boot would silently re-register dead values at scrape time.
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR") or os.environ.get(
        "prometheus_multiproc_dir"
    )
    if multiproc_dir and os.path.isdir(multiproc_dir):
        cleared = 0
        for entry in os.listdir(multiproc_dir):
            path = os.path.join(multiproc_dir, entry)
            if os.path.isfile(path) and entry.endswith(".db"):
                try:
                    os.unlink(path)
                    cleared += 1
                except OSError:
                    pass
        if cleared:
            logger.info(f"Cleared {cleared} stale prometheus multiproc files")


def on_reload(server):
    """Called when the master receives SIGHUP to reload."""
    logger.info("QueryfyAI reloading...")


def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    logger.warning(f"Worker {worker.pid} interrupted")


def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    logger.error(f"Worker {worker.pid} aborted")


def post_fork(server, worker):
    """Called just after a worker has been forked."""
    # Reinitialize connections per worker if needed
    pass


def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass


def pre_exec(server):
    """Called just before a new master process is forked."""
    logger.info("QueryfyAI forking master process")


def when_ready(server):
    """Called just after the server is started."""
    logger.info(f"QueryfyAI ready at {bind}")


def worker_exit(server, worker):
    """Called just after a worker has been killed."""
    logger.info(f"Worker {worker.pid} exiting")


def child_exit(server, worker):
    """Called from the master process after a worker exits.
    Mark the worker's prometheus_client mmap files for removal so they
    don't pollute scrape results with stale values. Required when
    PROMETHEUS_MULTIPROC_DIR is set (F20 — see backend/app/api/metrics.py).
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR") or os.environ.get(
        "prometheus_multiproc_dir"
    ):
        try:
            from prometheus_client import multiprocess
            multiprocess.mark_process_dead(worker.pid)
        except Exception as e:
            # Best-effort — don't block worker reaping on metrics housekeeping.
            logger.warning(f"prometheus mark_process_dead failed for {worker.pid}: {e}")
