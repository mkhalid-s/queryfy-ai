"""
Mock long-running query helpers (Step 1b).

Utilities for tests that need to simulate multi-minute data-lake
queries without actually taking multi-minute time. Two building blocks:

1. ``MockAsyncExecutor`` — implements ``AsyncExecutorProtocol`` with
   configurable lifecycle timings and optional progress emissions.
   Useful for Phase 3b driver-layer tests (cancellation semantics,
   progress plumbing) without needing a real driver.

2. ``simulate_progress_stream`` — async generator yielding progress
   payloads on a schedule. Drop it into tests that exercise the SSE
   heartbeat / progress merger without needing an executor.

Both use ``asyncio.sleep`` with fractional seconds so the whole
"long-running" query lifecycle fits inside a normal unit-test budget.
A real 5-minute BigQuery run is simulated in 0.5 seconds by scaling
the intervals down.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.services.async_executor_protocol import (
    AsyncExecutorProtocol,
    QueryHandle,
)


# --------------------------------------------------------------------------
# MockAsyncExecutor
# --------------------------------------------------------------------------


@dataclass
class MockAsyncExecutor(AsyncExecutorProtocol):
    """
    Fake async executor that walks through the protocol lifecycle on
    wall-clock intervals. Useful for exercising the Phase 3b plumbing
    (ToolContext.progress_emitter, timeout cancellation, fetch
    ordering) without a real driver.

    Args:
        db_type: The db_type string the handle will carry (e.g.
            "mock-bigquery").
        run_duration_s: How long the simulated query runs before
            transitioning to "complete". Set to 10+s to exercise
            cancellation code paths, <1s for fast happy-path tests.
        progress_interval_s: How often to emit progress between start
            and complete. ``None`` disables progress emission.
        progress_sequence: Iterable of dicts pushed via a registered
            progress callback in order. If fewer entries than
            ``run_duration_s / progress_interval_s``, the last entry
            is repeated.
        result_rows / result_columns: Fetched payload when the query
            completes.
        fail_after_s: If set, transitions to "failed" instead of
            "complete" at this offset.
        cancel_on_request: If True, ``cancel()`` actually cancels the
            internal run task; if False, it acknowledges but lets the
            run finish (useful for simulating drivers that can't
            actually kill a running query).
    """

    db_type: str = "mock"
    run_duration_s: float = 0.2
    progress_interval_s: Optional[float] = 0.05
    progress_sequence: List[Dict[str, Any]] = field(default_factory=list)
    result_rows: List[Dict[str, Any]] = field(default_factory=list)
    result_columns: List[str] = field(default_factory=list)
    fail_after_s: Optional[float] = None
    cancel_on_request: bool = True

    # Internal state — not part of the public fixture API.
    _status: str = field(default="pending", init=False)
    _start_time: float = field(default=0.0, init=False)
    _run_task: Optional[asyncio.Task] = field(default=None, init=False)
    _progress_emitter: Optional[Any] = field(default=None, init=False)
    _cancelled: bool = field(default=False, init=False)

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    async def start_query(self, sql: str, **kwargs: Any) -> QueryHandle:
        # A callable to push progress payloads through. Test callers can
        # pass it as ``progress_emitter=<callback>`` in kwargs to
        # simulate what ``ToolContext.progress_emitter`` would do in
        # production.
        self._progress_emitter = kwargs.get("progress_emitter")
        self._status = "running"
        self._start_time = asyncio.get_event_loop().time()
        self._cancelled = False
        self._run_task = asyncio.create_task(
            self._simulate_run(),
            name=f"mock_async_executor:{self.db_type}",
        )
        return QueryHandle(
            query_id=f"mock-{id(self)}",
            db_type=self.db_type,
            driver_state=self,
        )

    async def poll_status(self, handle: QueryHandle) -> str:
        return self._status

    async def fetch_results(
        self, handle: QueryHandle, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        if self._status != "complete":
            raise RuntimeError(
                f"fetch_results called while status={self._status}; "
                f"only valid when 'complete'"
            )
        rows = self.result_rows[:limit] if limit is not None else self.result_rows
        return {
            "rows": rows,
            "columns": self.result_columns,
            "row_count": len(rows),
        }

    async def cancel(self, handle: QueryHandle) -> bool:
        self._cancelled = True
        if self.cancel_on_request and self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
            self._status = "cancelled"
        return True

    async def get_progress(
        self, handle: QueryHandle
    ) -> Optional[Dict[str, Any]]:
        if not self.progress_sequence:
            return None
        # Return the "latest" scheduled progress entry based on elapsed
        # time. Simple saturating index.
        elapsed = asyncio.get_event_loop().time() - self._start_time
        if self.progress_interval_s is None or self.progress_interval_s <= 0:
            idx = len(self.progress_sequence) - 1
        else:
            idx = min(
                int(elapsed / self.progress_interval_s),
                len(self.progress_sequence) - 1,
            )
        return dict(self.progress_sequence[idx])

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    async def _simulate_run(self) -> None:
        """Drive the status machine over ``run_duration_s``."""
        try:
            tick = 0
            elapsed = 0.0
            while elapsed < self.run_duration_s:
                if (
                    self.fail_after_s is not None
                    and elapsed >= self.fail_after_s
                ):
                    self._status = "failed"
                    return

                step = min(
                    self.progress_interval_s or self.run_duration_s,
                    self.run_duration_s - elapsed,
                )
                await asyncio.sleep(step)
                elapsed += step
                tick += 1

                # Emit scheduled progress if caller wired an emitter.
                if (
                    self._progress_emitter is not None
                    and self.progress_sequence
                    and self.progress_interval_s is not None
                ):
                    idx = min(tick - 1, len(self.progress_sequence) - 1)
                    payload = dict(self.progress_sequence[idx])
                    try:
                        self._progress_emitter(payload)
                    except Exception:
                        pass
            self._status = "complete"
        except asyncio.CancelledError:
            self._status = "cancelled"
            raise


# --------------------------------------------------------------------------
# Lightweight progress stream — no executor needed
# --------------------------------------------------------------------------


async def simulate_progress_stream(
    events: List[Dict[str, Any]],
    interval_s: float = 0.05,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Yield each entry in ``events`` after waiting ``interval_s``.

    Drop into tests that exercise the SSE heartbeat / progress merger
    without needing a full async executor. Each yielded payload has
    the shape expected by ``ToolContext.progress_emitter``:

        {"bytes_scanned": int, "rows_read": int, "percent": float}

    Unused fields can be omitted.
    """
    for payload in events:
        await asyncio.sleep(interval_s)
        yield payload


# --------------------------------------------------------------------------
# Convenience factory for the common happy-path case
# --------------------------------------------------------------------------


def make_happy_path_executor(
    db_type: str = "mock-bigquery",
    row_count: int = 3,
) -> MockAsyncExecutor:
    """Quick factory for tests that just want an executor that completes."""
    return MockAsyncExecutor(
        db_type=db_type,
        run_duration_s=0.05,
        progress_interval_s=0.02,
        progress_sequence=[
            {"bytes_scanned": 1024, "percent": 25.0},
            {"bytes_scanned": 2048, "percent": 50.0},
            {"bytes_scanned": 4096, "percent": 100.0},
        ],
        result_rows=[{"id": i, "value": i * 10} for i in range(row_count)],
        result_columns=["id", "value"],
    )
