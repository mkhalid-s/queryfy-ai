"""
B2 — `get_column_context` query-awareness (Tier B retrieval P0 #2).

Closes the audit finding that `data_dictionary.get_column_context()`
ignores its `query` parameter and returns every column description for
the connection. With `FIX_QUERY_AWARE_COLUMN_CONTEXT=True`, the method
semantic-searches the column-descriptions vector collection and returns
only the top `MAX_COLUMNS_IN_CONTEXT` matches.

These smoke tests pin both paths so a future PR that flips the flag
(Tier B's first PR, gated by the recall@k procedural check in
.github/workflows/retrieval-recall.yml) can assert the legacy path
still works under flag=False and the new path uses the vector DB
correctly under flag=True.

Mock-only — patches the vector_db and the DB session. No real DB,
no real ChromaDB.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeCol:
    """Minimal stand-in for `ColumnDescription` ORM objects."""

    def __init__(
        self,
        id: str,
        table_name: str,
        column_name: str,
        description: str,
        sample_values: List[str] | None = None,
        is_pii: bool = False,
    ) -> None:
        self.id = id
        self.table_name = table_name
        self.column_name = column_name
        self.description = description
        self.sample_values = sample_values
        self.is_pii = is_pii


@pytest.fixture
def sample_columns() -> List[_FakeCol]:
    return [
        _FakeCol(
            id="col1",
            table_name="customers",
            column_name="customer_id",
            description="unique customer id",
            sample_values=["1", "2", "3"],
        ),
        _FakeCol(
            id="col2",
            table_name="orders",
            column_name="total_amount",
            description="order total in USD",
            sample_values=["99.50", "150.00"],
        ),
        _FakeCol(
            id="col3",
            table_name="orders",
            column_name="placed_at",
            description="order placement timestamp",
            sample_values=None,
            is_pii=False,
        ),
    ]


# ---------------------------------------------------------------------------
# Legacy (flag-off) path — UNCHANGED from pre-B2 behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_path_dumps_all_columns_when_flag_off(
    monkeypatch, sample_columns
) -> None:
    """With FIX_QUERY_AWARE_COLUMN_CONTEXT=False (the default), every
    active column for the connection is included. Same behaviour as
    pre-B2 — the existing prompt-pollution pattern is preserved
    intentionally until the flag flips with a measured recall@k."""
    from app.core.config import settings
    from app.services.data_dictionary import data_dictionary

    monkeypatch.setattr(settings, "FIX_QUERY_AWARE_COLUMN_CONTEXT", False)

    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = sample_columns

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=fake_result)

    class _SessionCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *args):
            return None

    with patch(
        "app.services.data_dictionary.get_db_session", lambda: _SessionCtx()
    ):
        context = await data_dictionary.get_column_context(
            query="show me top customers", connection_hash="hash1"
        )

    assert "Column Descriptions:" in context
    # All three columns present — the query is ignored on the legacy path.
    assert "customers.customer_id" in context
    assert "orders.total_amount" in context
    assert "orders.placed_at" in context


@pytest.mark.asyncio
async def test_legacy_path_when_query_empty_even_if_flag_on(
    monkeypatch, sample_columns
) -> None:
    """Even with flag=True, an empty query falls back to the legacy
    dump — the semantic-search path requires both a flag and a query
    (a blank query would match nothing usefully)."""
    from app.core.config import settings
    from app.services.data_dictionary import data_dictionary

    monkeypatch.setattr(settings, "FIX_QUERY_AWARE_COLUMN_CONTEXT", True)

    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = sample_columns

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=fake_result)

    class _SessionCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *args):
            return None

    with patch(
        "app.services.data_dictionary.get_db_session", lambda: _SessionCtx()
    ):
        context = await data_dictionary.get_column_context(
            query="", connection_hash="hash1"
        )

    assert "customers.customer_id" in context
    assert "orders.total_amount" in context


# ---------------------------------------------------------------------------
# Query-aware (flag-on) path — semantic-search + top-K
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_aware_path_returns_ranked_top_k(
    monkeypatch, sample_columns
) -> None:
    """With FIX_QUERY_AWARE_COLUMN_CONTEXT=True AND a non-empty query,
    only the columns the vector_db ranks as relevant are returned, in
    the rank order the vector_db produced."""
    from app.core.config import settings
    from app.services.data_dictionary import data_dictionary

    monkeypatch.setattr(settings, "FIX_QUERY_AWARE_COLUMN_CONTEXT", True)
    monkeypatch.setattr(settings, "MAX_COLUMNS_IN_CONTEXT", 2)

    # Stub _search_relevant_columns directly so the test doesn't depend
    # on vector_db internals — the contract under test is "rank order
    # from _search_relevant_columns is preserved in the output."
    async def _fake_search(query, connection_hash, table_names=None, limit=20):
        # Ranked: orders.total_amount first, then customers.customer_id.
        # orders.placed_at is excluded intentionally — top-K filtering.
        return ["col2", "col1"]

    monkeypatch.setattr(
        data_dictionary, "_search_relevant_columns", _fake_search
    )

    # DB fetch returns the same two columns (in arbitrary order — the
    # method must re-order them by the ranked_ids list).
    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = [
        c for c in sample_columns if c.id in ("col1", "col2")
    ]
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=fake_result)

    class _SessionCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *args):
            return None

    with patch(
        "app.services.data_dictionary.get_db_session", lambda: _SessionCtx()
    ):
        context = await data_dictionary.get_column_context(
            query="order revenue last month", connection_hash="hash1"
        )

    # Ranked-order preserved: total_amount should appear before customer_id
    idx_total = context.find("orders.total_amount")
    idx_customer = context.find("customers.customer_id")
    assert idx_total > -1 and idx_customer > -1
    assert idx_total < idx_customer, (
        "vector_db ranked order must be preserved in the returned "
        f"context; got total_amount at {idx_total}, customer_id at {idx_customer}"
    )
    # placed_at was excluded by top-K
    assert "placed_at" not in context


@pytest.mark.asyncio
async def test_query_aware_falls_back_when_vector_returns_empty(
    monkeypatch, sample_columns
) -> None:
    """When the vector search returns no matches (typical when the
    column collection is not yet indexed for this connection), the
    query-aware path falls back to the legacy dump so the caller
    still gets useful context."""
    from app.core.config import settings
    from app.services.data_dictionary import data_dictionary

    monkeypatch.setattr(settings, "FIX_QUERY_AWARE_COLUMN_CONTEXT", True)

    async def _empty_search(query, connection_hash, table_names=None, limit=20):
        return []

    monkeypatch.setattr(
        data_dictionary, "_search_relevant_columns", _empty_search
    )

    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = sample_columns
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=fake_result)

    class _SessionCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *args):
            return None

    with patch(
        "app.services.data_dictionary.get_db_session", lambda: _SessionCtx()
    ):
        context = await data_dictionary.get_column_context(
            query="anything", connection_hash="hash1"
        )

    # Fallback to legacy dump — all three columns
    assert "customers.customer_id" in context
    assert "orders.total_amount" in context
    assert "orders.placed_at" in context


# ---------------------------------------------------------------------------
# Defensive: _search_relevant_columns must never raise — exceptions
# would propagate to the SQL generator and crash the request.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_handles_missing_vector_db_gracefully(
    monkeypatch,
) -> None:
    """If vector_db is unavailable (ChromaDB not started, network
    partition), the search returns [] cleanly so the caller's
    fallback kicks in. Must never raise."""
    from app.services.data_dictionary import data_dictionary

    monkeypatch.setattr(data_dictionary, "_get_vector_db", lambda: None)

    result = await data_dictionary._search_relevant_columns(
        query="anything", connection_hash="hash1", limit=5
    )
    assert result == []


@pytest.mark.asyncio
async def test_search_emits_fallback_counter_on_vector_unavailable(
    monkeypatch,
) -> None:
    """Architect P1 — Pass 3 closeout: every fallback path emits a
    `queryfyai_retrieval_fallback_total{reason=...}` counter so
    operators can distinguish vector-db-down from no-results from
    exception. Without this signal, retrieval-quality regressions
    look identical to a healthy idle deployment."""
    import app.services.data_dictionary as dd_module
    from app.services.data_dictionary import data_dictionary

    emitted = []
    monkeypatch.setattr(
        dd_module, "_emit_retrieval_fallback", lambda reason: emitted.append(reason)
    )
    monkeypatch.setattr(data_dictionary, "_get_vector_db", lambda: None)

    await data_dictionary._search_relevant_columns(
        query="anything", connection_hash="hash1", limit=5
    )
    assert "vector_db_unavailable" in emitted


@pytest.mark.asyncio
async def test_search_emits_fallback_counter_on_exception(monkeypatch) -> None:
    """Every exception path emits the counter so a flaky vector_db
    is visible on the dashboard, not silently absorbed."""
    from unittest.mock import MagicMock

    import app.services.data_dictionary as dd_module
    from app.services.data_dictionary import data_dictionary

    emitted = []
    monkeypatch.setattr(
        dd_module, "_emit_retrieval_fallback", lambda reason: emitted.append(reason)
    )

    fake_vdb = MagicMock()
    fake_vdb.db_type = "chromadb"
    monkeypatch.setattr(data_dictionary, "_get_vector_db", lambda: fake_vdb)

    bad_collection = MagicMock()
    bad_collection.query.side_effect = RuntimeError("chroma down")
    monkeypatch.setattr(
        data_dictionary, "_get_collection", lambda name: bad_collection
    )

    result = await data_dictionary._search_relevant_columns(
        query="anything", connection_hash="hash1", limit=5
    )
    assert result == []
    assert "exception" in emitted


@pytest.mark.asyncio
async def test_search_handles_vector_db_exception_gracefully(
    monkeypatch,
) -> None:
    """Any exception from the vector DB collection is swallowed and
    the search returns [] so the legacy path takes over silently."""
    from app.services.data_dictionary import data_dictionary

    fake_vdb = MagicMock()
    fake_vdb.db_type = "chromadb"
    monkeypatch.setattr(data_dictionary, "_get_vector_db", lambda: fake_vdb)

    bad_collection = MagicMock()
    bad_collection.query.side_effect = RuntimeError("chroma down")
    monkeypatch.setattr(
        data_dictionary, "_get_collection", lambda name: bad_collection
    )

    result = await data_dictionary._search_relevant_columns(
        query="anything", connection_hash="hash1", limit=5
    )
    assert result == []


# ---------------------------------------------------------------------------
# Defensive: the flag default must be False so existing deployments
# don't silently flip into the new retrieval shape without a Tier B
# measurement PR.
# ---------------------------------------------------------------------------


def test_query_aware_flag_defaults_to_false() -> None:
    """Belt-and-braces: pristine `Settings()` reads False for the new
    flag. Catches a future PR that flips the default without taking
    the recall@k procedural gate."""
    from app.core.config import Settings

    fresh = Settings()
    assert fresh.FIX_QUERY_AWARE_COLUMN_CONTEXT is False, (
        "FIX_QUERY_AWARE_COLUMN_CONTEXT default changed from False. "
        "Per Tier B gate (.github/workflows/retrieval-recall.yml + F45 in "
        "tracker), this must stay off-by-default until a Tier B PR ships "
        "with before/after recall@k numbers measured via the harness."
    )
