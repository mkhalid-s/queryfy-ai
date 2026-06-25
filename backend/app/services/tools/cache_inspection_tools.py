"""
LLM drill-down tools for cached query results (Phase 4.2).

After ``execute_and_analyze`` runs, the full row set sits in
``result_cache`` under a ``rows_ref`` handle. The LLM gets the
analysis + a 20-row preview; these tools let it dig into the rest
without re-executing the SQL or pulling all rows into context.

Two tools:
  - ``get_cached_rows(rows_ref, offset, limit)`` — paginated raw rows.
    Hard-cap ``limit`` at 50 so the LLM never accidentally pulls
    9,000 rows into its context window.
  - ``inspect_cached_result(rows_ref, operation, params)`` —
    structured operations (filter, top_n, describe, group_summary,
    count_distinct). Each returns a small payload (≤ 5KB typical).

Tools never raise to the agent; they always return a JSON envelope
with ``success`` so the agent can read the error and decide what to
do next (existing pattern across query_tools.py).
"""

from __future__ import annotations

import json
import logging
import math
import statistics as stdlib_statistics
import time
from typing import Any, Dict, List, Optional

from app.services.tools.registry import ToolContext

logger = logging.getLogger(__name__)


# Hard cap so the LLM never accidentally fetches a fat slice into
# its context. Picked to fit comfortably alongside everything else
# in a single tool-result message (~50KB of context budget).
MAX_LLM_FETCH_ROWS = 50

# Rows actually returned in inspect_cached_result samples (filter,
# top_n preview etc.). Keep small — the LLM only needs concrete
# examples, not the whole filtered set.
INSPECT_SAMPLE_LIMIT = 10


def _safe_rows_ref(rows_ref: str) -> str:
    """rows_ref is ``result:{session_id}:{query_id}`` — the session_id
    half is the IDOR-boundary credential (compared via hmac in
    api/queries.py). INFO logs ship to centralized aggregators with
    long retention, so emit only the query_id suffix for correlation.
    """
    if not rows_ref:
        return ""
    parts = rows_ref.split(":")
    if len(parts) >= 3:
        return f"{parts[0]}:***:{parts[-1]}"
    return "***"


def _envelope_error(message: str, **extra: Any) -> str:
    """Standard error response shape — matches query_tools convention."""
    payload = {"success": False, "error": message}
    payload.update(extra)
    return json.dumps(payload)


def _envelope_ok(**fields: Any) -> str:
    payload = {"success": True}
    payload.update(fields)
    return json.dumps(payload, default=str)


def _emit_cache_metric(operation: str, result: str) -> None:
    """
    Increment ``queryfyai_result_cache_operations_total{operation, result}``.

    Lazy import so this module stays independent of the metrics layer
    at import time. Best-effort: never raises into the tool path.
    """
    try:
        from app.api.metrics import record_cache_operation

        record_cache_operation(operation, result)
    except Exception:  # pragma: no cover — metrics is best-effort
        pass


# --------------------------------------------------------------------------
# Tool 1: get_cached_rows — paginated raw access
# --------------------------------------------------------------------------


async def get_cached_rows(
    context: ToolContext,
    rows_ref: str,
    offset: int = 0,
    limit: int = 20,
) -> str:
    """
    Return up to ``limit`` rows from a cached query result, starting at
    ``offset``. Used when the LLM needs to reference specific rows by
    value (e.g. "show me the top three outliers we just saw").

    Hard-capped at ``MAX_LLM_FETCH_ROWS`` so the LLM can't pull a
    9000-row slice into its context.
    """
    from app.services.result_cache import result_cache

    # Preserve the caller's intent so the LLM can see that its
    # request was capped and pivot to a different tool
    # (inspect_cached_result.top_n / .group_summary) for larger slices.
    requested_limit = limit
    limit_capped_reason: Optional[str] = None

    if not rows_ref:
        return _envelope_error("rows_ref is required")

    if limit <= 0:
        limit = 20
    if limit > MAX_LLM_FETCH_ROWS:
        logger.info(
            "get_cached_rows: capping limit %d -> %d",
            limit,
            MAX_LLM_FETCH_ROWS,
        )
        limit = MAX_LLM_FETCH_ROWS
        limit_capped_reason = "max_50_per_call"

    if offset < 0:
        offset = 0

    # Structured log at completion so operators can measure cache
    # hit rate without standing up a metrics pipeline.
    t0 = time.monotonic()
    slice_ = result_cache.get_rows_slice(rows_ref, offset=offset, limit=limit)
    latency_ms = int((time.monotonic() - t0) * 1000)

    if slice_ is None:
        logger.info(
            "get_cached_rows.complete",
            extra={
                "rows_ref": _safe_rows_ref(rows_ref),
                "offset": offset,
                "limit": limit,
                "hit": False,
                "latency_ms": latency_ms,
                "rows_returned": 0,
            },
        )
        _emit_cache_metric("slice", "miss")
        return _envelope_error(
            f"rows_ref {rows_ref!r} not found (expired or never stored). "
            f"Re-run the query if you need this data.",
            rows_ref=rows_ref,
        )

    logger.info(
        "get_cached_rows.complete",
        extra={
            "rows_ref": _safe_rows_ref(rows_ref),
            "offset": slice_["offset"],
            "limit": slice_["limit"],
            "requested_limit": requested_limit,
            "hit": True,
            "latency_ms": latency_ms,
            "rows_returned": len(slice_["rows"]),
            "limit_capped_reason": limit_capped_reason,
        },
    )
    _emit_cache_metric("slice", "hit")

    return _envelope_ok(
        rows_ref=rows_ref,
        offset=slice_["offset"],
        limit=slice_["limit"],
        requested_limit=requested_limit,
        actual_limit=slice_["limit"],
        limit_capped_reason=limit_capped_reason,
        rows=slice_["rows"],
        columns=slice_["columns"],
        total_row_count=slice_["total_row_count"],
        has_more=slice_["has_more"],
    )


# --------------------------------------------------------------------------
# Tool 2: inspect_cached_result — structured operations
# --------------------------------------------------------------------------


async def inspect_cached_result(
    context: ToolContext,
    rows_ref: str,
    operation: str,
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Run a structured operation over a cached result and return a small
    payload describing the answer.

    Supported operations:
      - ``filter``: ``{"column": str, "op": "eq"|"ne"|"gt"|"gte"|"lt"|"lte"|"in"|"contains", "value": Any}``
      - ``top_n``: ``{"column": str, "n": int <= 20, "direction": "asc"|"desc"}``
      - ``describe``: ``{"column": str}`` — numeric stats for one column
      - ``group_summary``: ``{"group_by": str|List[str], "agg_column": str, "agg_fn": "sum"|"avg"|"count"|"min"|"max"}``
      - ``count_distinct``: ``{"column": str, "top": int <= 20}`` — top-N distinct values + counts
    """
    from app.services.result_cache import result_cache

    t0 = time.monotonic()

    if not rows_ref:
        return _envelope_error("rows_ref is required")

    cached = result_cache.get(rows_ref)
    if cached is None:
        # Log the miss path too so hit/miss ratio is observable
        # from the structured log stream alone.
        logger.info(
            "inspect_cached_result.complete",
            extra={
                "rows_ref": _safe_rows_ref(rows_ref),
                "operation": operation,
                "hit": False,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            },
        )
        _emit_cache_metric("inspect", "miss")
        return _envelope_error(
            f"rows_ref {rows_ref!r} not found (expired or never stored). "
            f"Re-run the query if you need this data.",
            rows_ref=rows_ref,
        )

    rows = cached.rows or []
    columns = cached.columns or []
    params = params or {}

    op = operation.lower().strip()
    op_ok = True
    try:
        if op == "filter":
            result_json = _op_filter(rows_ref, rows, columns, params)
        elif op == "top_n":
            result_json = _op_top_n(rows_ref, rows, columns, params)
        elif op == "describe":
            result_json = _op_describe(rows_ref, rows, params)
        elif op == "group_summary":
            result_json = _op_group_summary(rows_ref, rows, params)
        elif op == "count_distinct":
            result_json = _op_count_distinct(rows_ref, rows, params)
        else:
            result_json = _envelope_error(
                f"unknown operation {operation!r}. "
                f"Supported: filter, top_n, describe, group_summary, count_distinct",
                rows_ref=rows_ref,
            )
            op_ok = False
    except (KeyError, ValueError, TypeError) as e:
        result_json = _envelope_error(f"{op} failed: {e}", rows_ref=rows_ref)
        op_ok = False

    logger.info(
        "inspect_cached_result.complete",
        extra={
            "rows_ref": _safe_rows_ref(rows_ref),
            "operation": op,
            "hit": True,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "total_rows": len(rows),
        },
    )
    # "hit" here = the cache lookup succeeded; the structured operation
    # itself may still have failed inside the try block above (filter on
    # a missing column, unknown operation, etc.) — that case routes to
    # "error". Tracked via op_ok rather than parsing result_json so a
    # future _envelope_error format change can't silently flip the
    # metric signal.
    _emit_cache_metric("inspect", "hit" if op_ok else "error")
    return result_json


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


def _op_filter(
    rows_ref: str,
    rows: List[Dict[str, Any]],
    columns: List[str],
    params: Dict[str, Any],
) -> str:
    column = params.get("column")
    op = (params.get("op") or "eq").lower()
    value = params.get("value")
    if not column:
        raise ValueError("filter requires 'column'")
    if column not in columns:
        raise ValueError(f"column {column!r} not in result; available: {columns}")

    def _match(cell: Any) -> bool:
        if op == "eq":
            return cell == value
        if op == "ne":
            return cell != value
        if op == "gt":
            return cell is not None and cell > value
        if op == "gte":
            return cell is not None and cell >= value
        if op == "lt":
            return cell is not None and cell < value
        if op == "lte":
            return cell is not None and cell <= value
        if op == "in":
            return cell in (value or [])
        if op == "contains":
            return cell is not None and str(value) in str(cell)
        raise ValueError(
            f"unsupported op {op!r}; "
            f"use eq | ne | gt | gte | lt | lte | in | contains"
        )

    matched = [r for r in rows if _match(r.get(column))]
    sample = matched[:INSPECT_SAMPLE_LIMIT]
    return _envelope_ok(
        rows_ref=rows_ref,
        operation="filter",
        column=column,
        op=op,
        value=value,
        matched_row_count=len(matched),
        total_row_count=len(rows),
        sample=sample,
        sample_size=len(sample),
    )


def _op_top_n(
    rows_ref: str,
    rows: List[Dict[str, Any]],
    columns: List[str],
    params: Dict[str, Any],
) -> str:
    column = params.get("column")
    n = int(params.get("n") or 5)
    direction = (params.get("direction") or "desc").lower()
    if not column:
        raise ValueError("top_n requires 'column'")
    if column not in columns:
        raise ValueError(f"column {column!r} not in result; available: {columns}")
    if n <= 0:
        raise ValueError("n must be > 0")
    if n > 20:
        n = 20

    # Sort with None pushed to the end so they don't dominate top_n.
    def _key(row: Dict[str, Any]):
        v = row.get(column)
        return (v is None, v)

    sorted_rows = sorted(rows, key=_key, reverse=(direction == "desc"))
    top = sorted_rows[:n]
    return _envelope_ok(
        rows_ref=rows_ref,
        operation="top_n",
        column=column,
        direction=direction,
        n=n,
        rows=top,
        total_row_count=len(rows),
    )


def _op_describe(
    rows_ref: str,
    rows: List[Dict[str, Any]],
    params: Dict[str, Any],
) -> str:
    column = params.get("column")
    if not column:
        raise ValueError("describe requires 'column'")

    values: List[float] = []
    nulls = 0
    for r in rows:
        v = r.get(column)
        if v is None:
            nulls += 1
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if math.isnan(v) or math.isinf(v):
                continue
            values.append(float(v))

    if not values:
        return _envelope_ok(
            rows_ref=rows_ref,
            operation="describe",
            column=column,
            kind="non_numeric_or_empty",
            row_count=len(rows),
            nulls=nulls,
            note="No numeric values to describe — try count_distinct for categoricals.",
        )

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return _envelope_ok(
        rows_ref=rows_ref,
        operation="describe",
        column=column,
        kind="numeric",
        count=n,
        nulls=nulls,
        min=sorted_vals[0],
        max=sorted_vals[-1],
        mean=round(sum(sorted_vals) / n, 4),
        median=stdlib_statistics.median(sorted_vals),
        stdev=round(stdlib_statistics.stdev(sorted_vals), 4) if n > 1 else 0.0,
        p25=sorted_vals[max(0, int(n * 0.25) - 1)],
        p75=sorted_vals[min(n - 1, int(n * 0.75))],
    )


def _op_group_summary(
    rows_ref: str,
    rows: List[Dict[str, Any]],
    params: Dict[str, Any],
) -> str:
    group_by = params.get("group_by")
    agg_column = params.get("agg_column")
    agg_fn = (params.get("agg_fn") or "count").lower()
    if not group_by:
        raise ValueError("group_summary requires 'group_by'")
    keys: List[str] = [group_by] if isinstance(group_by, str) else list(group_by)

    if agg_fn not in ("count", "sum", "avg", "min", "max"):
        raise ValueError(
            f"agg_fn must be one of count|sum|avg|min|max, got {agg_fn!r}"
        )
    if agg_fn != "count" and not agg_column:
        raise ValueError(f"agg_fn={agg_fn} requires 'agg_column'")

    buckets: Dict[tuple, List[Any]] = {}
    for r in rows:
        bucket_key = tuple(r.get(k) for k in keys)
        buckets.setdefault(bucket_key, []).append(
            r.get(agg_column) if agg_column else None
        )

    out: List[Dict[str, Any]] = []
    for k, vals in buckets.items():
        row: Dict[str, Any] = dict(zip(keys, k))
        if agg_fn == "count":
            row["count"] = len(vals)
        else:
            numeric = [
                v for v in vals
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            if not numeric:
                row[agg_fn] = None
            elif agg_fn == "sum":
                row["sum"] = sum(numeric)
            elif agg_fn == "avg":
                row["avg"] = round(sum(numeric) / len(numeric), 4)
            elif agg_fn == "min":
                row["min"] = min(numeric)
            elif agg_fn == "max":
                row["max"] = max(numeric)
        out.append(row)

    sort_key = "count" if agg_fn == "count" else agg_fn
    out.sort(key=lambda r: (r.get(sort_key) is None, r.get(sort_key)), reverse=True)
    # Cap returned groups so the payload stays small.
    out = out[:50]

    return _envelope_ok(
        rows_ref=rows_ref,
        operation="group_summary",
        group_by=keys,
        agg_column=agg_column,
        agg_fn=agg_fn,
        groups=out,
        group_count=len(buckets),
        total_row_count=len(rows),
    )


def _op_count_distinct(
    rows_ref: str,
    rows: List[Dict[str, Any]],
    params: Dict[str, Any],
) -> str:
    column = params.get("column")
    top = int(params.get("top") or 10)
    if not column:
        raise ValueError("count_distinct requires 'column'")
    if top <= 0:
        top = 10
    if top > 20:
        top = 20

    counts: Dict[Any, int] = {}
    nulls = 0
    for r in rows:
        v = r.get(column)
        if v is None:
            nulls += 1
            continue
        try:
            counts[v] = counts.get(v, 0) + 1
        except TypeError:
            # Unhashable value (dict / list); skip
            continue

    sorted_pairs = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top_pairs = sorted_pairs[:top]
    return _envelope_ok(
        rows_ref=rows_ref,
        operation="count_distinct",
        column=column,
        distinct_count=len(counts),
        nulls=nulls,
        top=[{"value": v, "count": c} for v, c in top_pairs],
        total_row_count=len(rows),
    )
