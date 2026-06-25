"""
A5 smoke: queryfyai_active_sessions gauge is wired to session lifecycle.

Pre-A5 the gauge was defined at app/api/metrics.py:134 and the setter
update_active_sessions() at :367 was never called from anywhere — the
metric was permanently zero (a silent regression blind-spot the audit
flagged as F P1 #9).

These tests assert:
1. create_session() updates the active-sessions metric.
2. delete() updates the active-sessions metric.
3. The emitter is best-effort: a metrics import failure does NOT raise
   into the session lifecycle path.

Mock-only — no Redis, no network, fast.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.session_store import SessionStore


@pytest.fixture
def store() -> SessionStore:
    """Return a fresh in-memory SessionStore (no Redis client)."""
    inst = SessionStore.__new__(SessionStore)
    inst.redis_client = None
    inst.memory_store = {}
    import threading

    inst._memory_lock = threading.RLock()
    return inst


def test_create_session_updates_active_sessions_metric(store: SessionStore) -> None:
    """create_session() must call update_active_sessions with the new count."""
    with patch("app.api.metrics.update_active_sessions") as mock_update:
        store.create_session({"provider": "openai"}, {"db_type": "postgres"})
        mock_update.assert_called_once_with(1)

        store.create_session({"provider": "openai"}, {"db_type": "postgres"})
        # Second call should reflect the new count
        assert mock_update.call_args_list[-1].args == (2,)


def test_delete_updates_active_sessions_metric(store: SessionStore) -> None:
    """delete() must call update_active_sessions with the new count."""
    sid = store.create_session({"provider": "openai"}, {"db_type": "postgres"})
    with patch("app.api.metrics.update_active_sessions") as mock_update:
        store.delete(sid)
        mock_update.assert_called_once_with(0)


def test_emitter_swallows_metrics_failure(store: SessionStore) -> None:
    """
    A metrics import / call failure must NOT propagate into the session
    lifecycle. Sessions still get created/deleted; the gauge just stays
    at its previous value.
    """
    with patch(
        "app.api.metrics.update_active_sessions",
        side_effect=RuntimeError("metrics broken"),
    ):
        # Must not raise
        sid = store.create_session({"provider": "openai"}, {"db_type": "postgres"})
        assert sid in store.memory_store
        store.delete(sid)
        assert sid not in store.memory_store


def test_count_active_sessions_uses_memory_store_when_no_redis(
    store: SessionStore,
) -> None:
    """count_active_sessions() returns memory_store length without Redis."""
    assert store.count_active_sessions() == 0
    store.memory_store["a"] = {"id": "a"}
    store.memory_store["b"] = {"id": "b"}
    assert store.count_active_sessions() == 2


def test_count_active_sessions_uses_redis_when_available(store: SessionStore) -> None:
    """count_active_sessions() prefers Redis when redis_client is set."""
    mock_redis = MagicMock()
    mock_redis.keys.return_value = [b"session:x", b"session:y", b"session:z"]
    store.redis_client = mock_redis
    assert store.count_active_sessions() == 3
    mock_redis.keys.assert_called_once_with("session:*")


def test_count_active_sessions_falls_back_to_memory_on_redis_error(
    store: SessionStore,
) -> None:
    """If Redis keys() raises, fall back to memory_store count, not zero."""
    mock_redis = MagicMock()
    mock_redis.keys.side_effect = ConnectionError("redis down")
    store.redis_client = mock_redis
    store.memory_store["a"] = {"id": "a"}
    assert store.count_active_sessions() == 1
