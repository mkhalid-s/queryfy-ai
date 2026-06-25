"""
F20 — multi-worker Prometheus aggregation regression net.

The previous contrarian + SRE reviewers flagged that F20's
`MultiProcessCollector` wiring shipped with zero CI coverage —
"first multi-worker scrape happens in production." Phase C wired
alerts that depend on these gauges being correct under N workers.

These tests spawn subprocesses (with PROMETHEUS_MULTIPROC_DIR set)
so the prometheus_client global REGISTRY starts clean. Each
subprocess simulates one "worker" writing to the shared mmap files;
the parent test process then aggregates and verifies scrape output.

This is not a substitute for a real gunicorn integration test
(F52 tracks that), but it pins the load-bearing invariants:
  - mmap files written per pid
  - MultiProcessCollector reads them across pids
  - Counter aggregation sums correctly
  - `mark_process_dead` reaps gauge files

Each test is its own subprocess invocation — slow vs. unit (~200 ms
per test) but clean isolation, no module-reload gymnastics.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _run_subprocess(multiproc_dir: Path, script: str) -> str:
    """Run a Python snippet in a subprocess with PROMETHEUS_MULTIPROC_DIR
    set. Returns the captured stdout. Raises on non-zero exit so test
    failures surface the subprocess error.
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env={
            "PROMETHEUS_MULTIPROC_DIR": str(multiproc_dir),
            "PATH": __import__("os").environ.get("PATH", ""),
            "PYTHONPATH": __import__("os").environ.get("PYTHONPATH", ""),
        },
        cwd=str(Path(__file__).resolve().parents[2]),  # backend/
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"subprocess failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


def test_multiproc_counter_aggregates_across_workers(tmp_path: Path) -> None:
    """Two subprocesses ("workers") write to the same Counter; the
    third aggregates via MultiProcessCollector and confirms the sum.
    """
    multiproc_dir = tmp_path / "prometheus_multiproc"
    multiproc_dir.mkdir()

    write_script = """
        import app.api.metrics as m
        assert m.PROMETHEUS_MULTIPROC, "multiproc not detected in subprocess"
        m.result_cache_operations_total.labels(operation='get', result='hit').inc(5)
        print('worker_ok')
    """
    out1 = _run_subprocess(multiproc_dir, write_script)
    out2 = _run_subprocess(multiproc_dir, write_script)
    assert "worker_ok" in out1 and "worker_ok" in out2

    aggregate_script = """
        from prometheus_client import CollectorRegistry, generate_latest, multiprocess
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        text = generate_latest(registry).decode('utf-8')
        print('---SCRAPE---')
        print(text)
        print('---END---')
    """
    out = _run_subprocess(multiproc_dir, aggregate_script)
    assert "queryfyai_result_cache_operations_total" in out
    # Two workers, each +5 → sum = 10
    assert 'queryfyai_result_cache_operations_total{operation="get",result="hit"} 10.0' in out, (
        f"Counter aggregation across 2 workers should sum to 10. Got:\n{out}"
    )


def test_multiproc_gauge_livemax_returns_max_across_workers(
    tmp_path: Path,
) -> None:
    """Two workers write different values to a `livemax` Gauge; the
    aggregator returns the max. This is the exact semantics F20
    promised for `active_sessions` and `mcp_enabled`."""
    multiproc_dir = tmp_path / "prometheus_multiproc"
    multiproc_dir.mkdir()

    # Worker A writes 12.
    _run_subprocess(
        multiproc_dir,
        "import app.api.metrics as m; m.active_sessions.set(12); print('a_done')",
    )
    # Worker B writes 47.
    _run_subprocess(
        multiproc_dir,
        "import app.api.metrics as m; m.active_sessions.set(47); print('b_done')",
    )
    # Worker C writes 5 (lower than the prior max — livemax should still surface 47).
    _run_subprocess(
        multiproc_dir,
        "import app.api.metrics as m; m.active_sessions.set(5); print('c_done')",
    )

    aggregate_script = """
        from prometheus_client import CollectorRegistry, generate_latest, multiprocess
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        text = generate_latest(registry).decode('utf-8')
        print(text)
    """
    out = _run_subprocess(multiproc_dir, aggregate_script)
    assert "queryfyai_active_sessions 47.0" in out, (
        f"livemax should aggregate to max=47 across 3 workers (12, 47, 5). Got:\n{out}"
    )


def test_multiproc_mark_process_dead_cleans_gauge_file(tmp_path: Path) -> None:
    """`prometheus_client.multiprocess.mark_process_dead(pid)` reaps
    the dead worker's gauge mmap file. This is what gunicorn's
    `child_exit` hook calls — without it, dead-worker values would
    accumulate forever."""
    multiproc_dir = tmp_path / "prometheus_multiproc"
    multiproc_dir.mkdir()

    # Worker writes a gauge value, then we ask the same process to
    # mark itself dead. Verify the gauge file is gone.
    cleanup_script = """
        import os
        import app.api.metrics as m
        m.active_sessions.set(99)
        pid = os.getpid()
        from prometheus_client import multiprocess
        # Before mark_process_dead:
        import os
        d = os.environ['PROMETHEUS_MULTIPROC_DIR']
        before = sorted(f for f in os.listdir(d) if str(pid) in f)
        multiprocess.mark_process_dead(pid)
        after = sorted(f for f in os.listdir(d) if str(pid) in f)
        print('PID', pid)
        print('BEFORE', before)
        print('AFTER', after)
    """
    out = _run_subprocess(multiproc_dir, cleanup_script)
    # The gauge_livemax file for the dead pid should have been removed.
    # (Counter files persist — they're accumulators meant to outlive
    # the worker. mark_process_dead only reaps gauge / live-mode files.)
    assert "gauge_livemax_" not in out.split("AFTER")[1], (
        f"mark_process_dead should remove gauge_livemax_<pid>.db. Got:\n{out}"
    )


def test_metrics_module_fails_loud_when_multiproc_dir_missing(
    tmp_path: Path,
) -> None:
    """Pins the contrarian-flagged edge case: if
    PROMETHEUS_MULTIPROC_DIR is set but the dir does NOT exist,
    metric construction crashes at module import (the Info gauge
    constructor opens an mmap file in the configured dir).

    This is HARD failure at startup — which is the right behaviour for
    production deploys: loud fail beats silent degradation at first
    scrape. The gunicorn `on_starting` hook in `backend/gunicorn.conf.py`
    defensively scans the dir for stale files (and would itself raise
    if the dir is missing AND not creatable). This test pins the
    actual failure shape so a future refactor that accidentally moves
    the error to scrape time is caught.

    F52 tracks a friendlier "PROMETHEUS_MULTIPROC_DIR=/path does not
    exist" message at module init time — for now, the raw
    FileNotFoundError IS the loud-fail signal.
    """
    missing = tmp_path / "does_not_exist"
    # Note: do NOT mkdir — we want to test the missing-dir case.
    import_script = """
        import app.api.metrics
        print('unexpectedly_succeeded')
    """
    with pytest.raises(RuntimeError, match="FileNotFoundError"):
        _run_subprocess(missing, import_script)
