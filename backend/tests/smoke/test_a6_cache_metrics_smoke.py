"""
A6 smoke: queryfyai_result_cache_operations_total counter is wired at
both the storage layer (result_cache.get/store) and the tool layer
(get_cached_rows / inspect_cached_result).

Pre-A6 there was no Prometheus metric for cache operations — the only
signal was structured log lines, which aren't scrapable. Source:
Reviewer E + F P1 #10.

These tests assert each call site emits exactly one metric with the
correct (operation, result) label pair. Mock-only — no Redis.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from app.services.result_cache import ResultCache
from app.services.tools.cache_inspection_tools import (
    get_cached_rows,
    inspect_cached_result,
)


@pytest.fixture
def cache(monkeypatch) -> ResultCache:
    """Fresh in-memory ResultCache (no Redis)."""
    inst = ResultCache.__new__(ResultCache)
    import threading
    from collections import OrderedDict

    inst.redis_client = None
    inst._memory_store = OrderedDict()
    inst._memory_lock = threading.Lock()
    return inst


def _make_context():
    """Minimal ToolContext shim for the cache-inspection tools."""

    class _Ctx:
        session_id = "s1"
        connection_url = None
        db_config = None

    return _Ctx()


# ---------------------------------------------------------------------------
# Storage layer (result_cache.py)
# ---------------------------------------------------------------------------


def test_store_emits_store_hit(cache: ResultCache) -> None:
    with patch("app.api.metrics.record_cache_operation") as mock:
        cache.store(
            session_id="s1",
            query_id="q1",
            sql="SELECT 1",
            columns=["a"],
            rows=[{"a": 1}],
        )
        mock.assert_called_once_with("store", "hit")


def test_get_emits_get_hit_on_present(cache: ResultCache) -> None:
    cache.store(
        session_id="s1",
        query_id="q1",
        sql="SELECT 1",
        columns=["a"],
        rows=[{"a": 1}],
    )
    with patch("app.api.metrics.record_cache_operation") as mock:
        result = cache.get("result:s1:q1")
        assert result is not None
        mock.assert_called_once_with("get", "hit")


def test_get_emits_get_miss_on_absent(cache: ResultCache) -> None:
    with patch("app.api.metrics.record_cache_operation") as mock:
        result = cache.get("result:nonexistent:never")
        assert result is None
        mock.assert_called_once_with("get", "miss")


def test_metric_emission_is_best_effort(cache: ResultCache) -> None:
    """A broken metrics layer must not propagate into the cache path."""
    with patch(
        "app.api.metrics.record_cache_operation",
        side_effect=RuntimeError("metrics broken"),
    ):
        rows_ref = cache.store(
            session_id="s1",
            query_id="q1",
            sql="SELECT 1",
            columns=["a"],
            rows=[{"a": 1}],
        )
        assert rows_ref == "result:s1:q1"
        # And the read path also doesn't propagate
        result = cache.get(rows_ref)
        assert result is not None


# ---------------------------------------------------------------------------
# Tool layer (cache_inspection_tools.py)
# ---------------------------------------------------------------------------


def test_get_cached_rows_miss_emits_slice_miss(monkeypatch) -> None:
    """get_cached_rows on a missing rows_ref should emit ('slice', 'miss')."""
    from app.services import result_cache as rc_module

    # Patch the module-level singleton so the tool sees an empty cache
    empty_cache = ResultCache.__new__(ResultCache)
    import threading
    from collections import OrderedDict

    empty_cache.redis_client = None
    empty_cache._memory_store = OrderedDict()
    empty_cache._memory_lock = threading.Lock()
    monkeypatch.setattr(rc_module, "result_cache", empty_cache)

    with patch(
        "app.services.tools.cache_inspection_tools._emit_cache_metric"
    ) as mock:
        out = asyncio.run(
            get_cached_rows(_make_context(), rows_ref="result:missing:x")
        )
        payload = json.loads(out)
        assert payload["success"] is False
        mock.assert_called_once_with("slice", "miss")


def test_get_cached_rows_hit_emits_slice_hit(monkeypatch) -> None:
    """A populated cache should make get_cached_rows emit ('slice', 'hit')."""
    from app.services import result_cache as rc_module

    populated = ResultCache.__new__(ResultCache)
    import threading
    from collections import OrderedDict

    populated.redis_client = None
    populated._memory_store = OrderedDict()
    populated._memory_lock = threading.Lock()
    rows_ref = populated.store(
        session_id="s1",
        query_id="q1",
        sql="SELECT 1",
        columns=["a"],
        rows=[{"a": 1}, {"a": 2}, {"a": 3}],
    )
    monkeypatch.setattr(rc_module, "result_cache", populated)

    with patch(
        "app.services.tools.cache_inspection_tools._emit_cache_metric"
    ) as mock:
        out = asyncio.run(
            get_cached_rows(_make_context(), rows_ref=rows_ref, offset=0, limit=10)
        )
        payload = json.loads(out)
        assert payload["success"] is True
        mock.assert_called_once_with("slice", "hit")


def test_inspect_cached_result_miss_emits_inspect_miss(monkeypatch) -> None:
    """inspect_cached_result on a missing rows_ref emits ('inspect', 'miss')."""
    from app.services import result_cache as rc_module

    empty_cache = ResultCache.__new__(ResultCache)
    import threading
    from collections import OrderedDict

    empty_cache.redis_client = None
    empty_cache._memory_store = OrderedDict()
    empty_cache._memory_lock = threading.Lock()
    monkeypatch.setattr(rc_module, "result_cache", empty_cache)

    with patch(
        "app.services.tools.cache_inspection_tools._emit_cache_metric"
    ) as mock:
        out = asyncio.run(
            inspect_cached_result(
                _make_context(),
                rows_ref="result:missing:x",
                operation="describe",
                params={"column": "a"},
            )
        )
        payload = json.loads(out)
        assert payload["success"] is False
        mock.assert_called_once_with("inspect", "miss")


def test_inspect_cached_result_hit_emits_inspect_hit(monkeypatch) -> None:
    """A successful inspect emits ('inspect', 'hit')."""
    from app.services import result_cache as rc_module

    populated = ResultCache.__new__(ResultCache)
    import threading
    from collections import OrderedDict

    populated.redis_client = None
    populated._memory_store = OrderedDict()
    populated._memory_lock = threading.Lock()
    rows_ref = populated.store(
        session_id="s1",
        query_id="q1",
        sql="SELECT * FROM t",
        columns=["a"],
        rows=[{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}, {"a": 5}],
    )
    monkeypatch.setattr(rc_module, "result_cache", populated)

    with patch(
        "app.services.tools.cache_inspection_tools._emit_cache_metric"
    ) as mock:
        out = asyncio.run(
            inspect_cached_result(
                _make_context(),
                rows_ref=rows_ref,
                operation="describe",
                params={"column": "a"},
            )
        )
        payload = json.loads(out)
        assert payload["success"] is True
        mock.assert_called_once_with("inspect", "hit")


def test_inspect_cached_result_error_emits_inspect_error(monkeypatch) -> None:
    """
    Cache hit but the structured operation itself fails (unknown op
    or bad params) — must emit ('inspect', 'error'), not 'hit'.

    Guards against the metric being driven by string-matching into a
    JSON envelope, which would silently flip if `_envelope_error`'s
    format ever changes.
    """
    from app.services import result_cache as rc_module

    populated = ResultCache.__new__(ResultCache)
    import threading
    from collections import OrderedDict

    populated.redis_client = None
    populated._memory_store = OrderedDict()
    populated._memory_lock = threading.Lock()
    rows_ref = populated.store(
        session_id="s1",
        query_id="q1",
        sql="SELECT * FROM t",
        columns=["a"],
        rows=[{"a": 1}, {"a": 2}, {"a": 3}],
    )
    monkeypatch.setattr(rc_module, "result_cache", populated)

    with patch(
        "app.services.tools.cache_inspection_tools._emit_cache_metric"
    ) as mock:
        out = asyncio.run(
            inspect_cached_result(
                _make_context(),
                rows_ref=rows_ref,
                operation="totally_made_up_op",
                params={},
            )
        )
        payload = json.loads(out)
        assert payload["success"] is False
        mock.assert_called_once_with("inspect", "error")
