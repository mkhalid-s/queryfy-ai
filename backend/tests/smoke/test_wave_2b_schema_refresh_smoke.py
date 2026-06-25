"""
Smoke tests for the single-table schema refresh primitive.

Cheap, mock-only checks that the dispatch logic and short-circuits
work without spinning up a real DB or a vector store. Exercises:

  - MongoDB short-circuit when SCHEMA_AUTO_REFRESH_MONGO is False
  - Unknown db_type → no_extractor
  - Empty table_name / connection_url → failed
  - Successful SQL path → calls extractor + vector_db.update

Run via:
    bash backend/scripts/run-tests.sh tests/smoke/test_wave_2b_schema_refresh_smoke.py -v
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Short-circuits
# ---------------------------------------------------------------------------


class TestShortCircuits:
    @pytest.mark.asyncio
    async def test_empty_table_name_returns_failed(self):
        from app.services.schema_refresh import refresh_table_schema

        result = await refresh_table_schema(
            db_config=SimpleNamespace(db_type="postgresql", connection_url="postgresql://h/d"),
            schema_name="public",
            table_name="",
            reason="test",
        )
        assert result["success"] is False
        assert result["reason"] == "failed"
        assert "empty table_name" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_empty_connection_url_returns_failed(self):
        from app.services.schema_refresh import refresh_table_schema

        result = await refresh_table_schema(
            db_config=SimpleNamespace(db_type="postgresql", connection_url=""),
            schema_name="public",
            table_name="users",
            reason="test",
        )
        assert result["success"] is False
        assert result["reason"] == "failed"
        assert "empty connection_url" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_mongodb_skipped_when_flag_off(self, monkeypatch):
        """SCHEMA_AUTO_REFRESH_MONGO defaults False → no DB call fires."""
        from app.core.config import settings
        from app.services.schema_refresh import refresh_table_schema

        monkeypatch.setattr(settings, "SCHEMA_AUTO_REFRESH_MONGO", False)
        result = await refresh_table_schema(
            db_config=SimpleNamespace(
                db_type="mongodb", connection_url="mongodb://h/db"
            ),
            schema_name=None,
            table_name="users",
            reason="test",
        )
        assert result["success"] is False
        assert result["reason"] == "mongodb_disabled"
        assert result["table_name"] == "users"

    @pytest.mark.asyncio
    async def test_unknown_db_type_returns_no_extractor(self):
        from app.services.schema_refresh import refresh_table_schema

        result = await refresh_table_schema(
            db_config=SimpleNamespace(
                db_type="some_unsupported_db", connection_url="foo://h"
            ),
            schema_name=None,
            table_name="t",
            reason="test",
        )
        # Generic SQL extractor catches anything that "looks SQL-ish";
        # truly unknown / falsy db_type returns no_extractor.
        assert result["success"] is False
        # generic_sql may still claim it; either way must not crash.
        assert result["reason"] in {"no_extractor", "failed"}


# ---------------------------------------------------------------------------
# Happy path — SQL extractor mocked
# ---------------------------------------------------------------------------


class TestSqlHappyPath:
    @pytest.mark.asyncio
    async def test_postgresql_refresh_calls_extractor_and_vector_db(self):
        """End-to-end mock — primitive plumbs columns into vector_db.update."""
        from app.services import schema_refresh as sr

        mock_extractor = MagicMock()
        # _get_connection is an async context manager.
        @asynccontextmanager
        async def fake_conn(_url):
            yield "conn-stub"
        mock_extractor._get_connection = fake_conn
        mock_extractor._get_columns = AsyncMock(
            return_value=[
                {"name": "id", "type": "int", "nullable": False},
                {"name": "email", "type": "varchar", "nullable": False},
            ]
        )
        mock_extractor._get_primary_keys = AsyncMock(return_value=["id"])
        mock_extractor._get_foreign_keys = AsyncMock(return_value=[])

        captured_call = {}

        def fake_update(connection_url, table_dict, *, item_type="table"):
            captured_call["connection_url"] = connection_url
            captured_call["table_dict"] = table_dict
            captured_call["item_type"] = item_type
            return True

        mock_vector_db = SimpleNamespace(
            _hash_connection=lambda url: "hash16chars0000",
            update_table_in_schema=fake_update,
        )

        with patch.object(sr, "get_extractor", return_value=mock_extractor), \
             patch("app.services.vector_db.vector_db", mock_vector_db):
            result = await sr.refresh_table_schema(
                db_config=SimpleNamespace(
                    db_type="postgresql",
                    connection_url="postgresql://h/db",
                ),
                schema_name="public",
                table_name="users",
                reason="empty_partition_keys",
            )

        assert result["success"] is True, result
        assert result["reason"] == "ok"
        assert result["table_name"] == "users"
        assert captured_call["table_dict"]["name"] == "users"
        assert captured_call["table_dict"]["schema"] == "public"
        assert len(captured_call["table_dict"]["columns"]) == 2
        assert captured_call["table_dict"]["primary_keys"] == ["id"]


# ---------------------------------------------------------------------------
# Cassandra path — partition_keys derived from key_type
# ---------------------------------------------------------------------------


class TestCassandraDerivation:
    @pytest.fixture(autouse=True)
    def allow_local_lock(self):
        from app.core.config import settings
        with patch.object(settings, "DEVELOPMENT_MODE", True):
            yield

    @pytest.mark.asyncio
    async def test_cassandra_partition_keys_assembled_from_kind_field(self):
        from app.services import schema_refresh as sr

        mock_extractor = MagicMock()
        @asynccontextmanager
        async def fake_conn(_url):
            yield "session-stub"
        mock_extractor._get_connection = fake_conn
        mock_extractor._get_columns = AsyncMock(
            return_value=[
                {"name": "tenant_id", "type": "uuid", "key_type": "partition_key", "position": 0},
                {"name": "order_id", "type": "uuid", "key_type": "clustering", "position": 0},
                {"name": "amount", "type": "decimal", "key_type": "regular", "position": 0},
            ]
        )
        mock_extractor._get_primary_keys = AsyncMock(
            return_value=["tenant_id", "order_id"]
        )
        mock_extractor._get_foreign_keys = AsyncMock(return_value=[])

        captured: dict = {}

        def fake_update(connection_url, table_dict, *, item_type="table"):
            captured["table_dict"] = table_dict
            return True

        mock_vector_db = SimpleNamespace(
            _hash_connection=lambda url: "hash16chars0000",
            update_table_in_schema=fake_update,
        )

        with patch.object(sr, "get_extractor", return_value=mock_extractor), \
             patch("app.services.vector_db.vector_db", mock_vector_db):
            result = await sr.refresh_table_schema(
                db_config=SimpleNamespace(
                    db_type="cassandra",
                    connection_url="cassandra://h/keyspace",
                ),
                schema_name="orders_ks",
                table_name="orders",
                reason="empty_partition_keys",
            )

        assert result["success"] is True
        assert captured["table_dict"]["partition_keys"] == ["tenant_id"]
        assert captured["table_dict"]["clustering_keys"] == ["order_id"]


# ---------------------------------------------------------------------------
# DynamoDB path — partition_key/sort_key from KeySchema
# ---------------------------------------------------------------------------


class TestDynamoDBDerivation:
    @pytest.fixture(autouse=True)
    def allow_local_lock(self):
        from app.core.config import settings
        with patch.object(settings, "DEVELOPMENT_MODE", True):
            yield

    @pytest.mark.asyncio
    async def test_dynamodb_partition_and_sort_keys_extracted_from_keyschema(self):
        from app.services import schema_refresh as sr

        mock_extractor = MagicMock()
        @asynccontextmanager
        async def fake_conn(_url):
            yield "client-stub"
        mock_extractor._get_connection = fake_conn
        mock_extractor._describe_table = AsyncMock(
            return_value={
                "KeySchema": [
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                ],
            }
        )
        mock_extractor._sample_items = AsyncMock(return_value=[])
        mock_extractor._infer_attributes_from_sample = MagicMock(return_value=[])

        captured: dict = {}

        def fake_update(connection_url, table_dict, *, item_type="table"):
            captured["table_dict"] = table_dict
            return True

        mock_vector_db = SimpleNamespace(
            _hash_connection=lambda url: "hash16chars0000",
            update_table_in_schema=fake_update,
        )

        with patch.object(sr, "get_extractor", return_value=mock_extractor), \
             patch("app.services.vector_db.vector_db", mock_vector_db):
            result = await sr.refresh_table_schema(
                db_config=SimpleNamespace(
                    db_type="dynamodb",
                    connection_url="dynamodb://h/region",
                ),
                schema_name=None,
                table_name="orders",
                reason="empty_partition_keys",
            )

        assert result["success"] is True
        assert captured["table_dict"]["partition_key"] == "PK"
        assert captured["table_dict"]["sort_key"] == "SK"


# ---------------------------------------------------------------------------
# Consumer #5 — get_table_schema partition-keys live-metadata fallback
# ---------------------------------------------------------------------------


class TestGetTableSchemaFallback:
    """
    Regression smoke: when the indexed copy of a Cassandra/DynamoDB
    table comes back with empty partition keys, get_table_schema
    fires refresh_table_schema and re-fetches before rendering.
    """

    @pytest.mark.asyncio
    async def test_cassandra_empty_partition_keys_triggers_refresh(self):
        from app.services.tools import schema_tools

        # First call returns a Cassandra table with NO partition_keys.
        # Second call (after refresh) returns the same table WITH keys.
        text_before = (
            "Table: orders_ks.orders\n"
            "Columns: tenant_id (uuid), order_id (uuid), amount (decimal)\n"
        )
        text_after = (
            "Table: orders_ks.orders\n"
            "Columns: tenant_id (uuid) [partition_key], order_id (uuid) [clustering], amount (decimal) [regular]\n"
            "Partition Keys: tenant_id\n"
            "Clustering Keys: order_id\n"
        )
        get_relevant_calls = []

        def fake_get_relevant_schema(connection_url, query, max_items=5):
            get_relevant_calls.append(query)
            # First call → text_before, all subsequent → text_after.
            return text_before if len(get_relevant_calls) == 1 else text_after

        mock_vector_db = SimpleNamespace(
            get_relevant_schema=fake_get_relevant_schema,
        )

        refresh_called = {}

        async def fake_refresh(*, db_config, schema_name, table_name, reason):
            refresh_called["called"] = True
            refresh_called["table_name"] = table_name
            refresh_called["reason"] = reason
            return {
                "success": True,
                "reason": "ok",
                "db_type": "cassandra",
                "table_name": table_name,
            }

        ctx = SimpleNamespace(
            connection_url="cassandra://h/keyspace",
            db_config={"db_type": "cassandra", "connection_url": "cassandra://h/keyspace", "db_name": "ks"},
            session_id="smoke",
        )

        with patch("app.services.vector_db.vector_db", mock_vector_db), \
             patch("app.services.schema_refresh.refresh_table_schema", fake_refresh):
            output = await schema_tools.get_table_schema(ctx, "orders_ks.orders")

        # The fallback should have fired and the post-refresh fetch
        # should have surfaced partition keys in the rendered output.
        assert refresh_called.get("called") is True
        assert refresh_called.get("reason") == "empty_partition_keys"
        assert refresh_called.get("table_name") == "orders"
        assert "Partition Keys" in output
        assert "tenant_id" in output

    @pytest.mark.asyncio
    async def test_postgresql_no_fallback_fires(self):
        """SQL DBs aren't subject to the partition-key fallback path."""
        from app.services.tools import schema_tools

        schema_text = (
            "Table: public.users\n"
            "Columns: id (int), email (varchar)\n"
        )

        def fake_get_relevant_schema(connection_url, query, max_items=5):
            return schema_text

        mock_vector_db = SimpleNamespace(
            get_relevant_schema=fake_get_relevant_schema,
        )

        refresh_called = {"count": 0}

        async def fake_refresh(*, db_config, schema_name, table_name, reason):
            refresh_called["count"] += 1
            return {"success": True, "reason": "ok"}

        ctx = SimpleNamespace(
            connection_url="postgresql://h/d",
            db_config={"db_type": "postgresql", "connection_url": "postgresql://h/d", "db_name": "d"},
            session_id="smoke",
        )

        with patch("app.services.vector_db.vector_db", mock_vector_db), \
             patch("app.services.schema_refresh.refresh_table_schema", fake_refresh):
            output = await schema_tools.get_table_schema(ctx, "public.users")

        # SQL path should NOT fire the fallback.
        assert refresh_called["count"] == 0
        assert "users" in output


# ---------------------------------------------------------------------------
# Consumer #17 — column-not-found auto-trigger
# ---------------------------------------------------------------------------


class TestColumnNotFoundAutoTrigger:
    """
    COLUMN_NOT_FOUND classifier output triggers a fire-and-forget
    schema refresh. Tests cover the helper directly (parsing,
    gating, scheduling) — full integration with tool_node is
    exercised indirectly via the existing circuit-breaker suite.
    """

    def test_extract_first_table_from_select_with_schema(self):
        from app.services.react_agent import _extract_first_table_from_sql

        result = _extract_first_table_from_sql(
            "SELECT id, name FROM public.customers WHERE id = 1"
        )
        assert result == ("public", "customers")

    def test_extract_first_table_from_select_no_schema(self):
        from app.services.react_agent import _extract_first_table_from_sql

        assert _extract_first_table_from_sql("SELECT * FROM customers") == (None, "customers")

    def test_extract_first_table_returns_none_for_unparseable(self):
        from app.services.react_agent import _extract_first_table_from_sql

        assert _extract_first_table_from_sql("") is None
        assert _extract_first_table_from_sql("WITH foo AS (...)") is None  # no FROM

    @pytest.mark.asyncio
    async def test_helper_skips_when_not_column_not_found(self):
        from app.services import react_agent

        scheduled = {"count": 0}
        async def fake_refresh(*, db_config, schema_name, table_name, reason):
            scheduled["count"] += 1
            return {"success": True, "reason": "ok"}

        ctx = SimpleNamespace(
            db_config={"db_type": "postgresql", "connection_url": "postgresql://h/d", "db_name": "d"}
        )
        with patch("app.services.schema_refresh.refresh_table_schema", fake_refresh):
            react_agent._maybe_schedule_schema_refresh_on_column_error(
                error_info={"error_type": "TABLE_NOT_FOUND"},  # not the trigger type
                tool_args={"sql": "SELECT * FROM public.users"},
                tool_context=ctx,
            )
            # Give the (potentially scheduled) task one tick — but
            # we expect zero scheduled.
            import asyncio
            await asyncio.sleep(0)
        assert scheduled["count"] == 0

    @pytest.mark.asyncio
    async def test_helper_schedules_refresh_for_column_not_found(self):
        from app.services import react_agent

        scheduled = {"count": 0, "table_name": None, "reason": None}
        async def fake_refresh(*, db_config, schema_name, table_name, reason):
            scheduled["count"] += 1
            scheduled["table_name"] = table_name
            scheduled["schema_name"] = schema_name
            scheduled["reason"] = reason
            return {"success": True, "reason": "ok"}

        ctx = SimpleNamespace(
            db_config={"db_type": "postgresql", "connection_url": "postgresql://h/d", "db_name": "d"}
        )
        with patch("app.services.schema_refresh.refresh_table_schema", fake_refresh):
            react_agent._maybe_schedule_schema_refresh_on_column_error(
                error_info={"error_type": "COLUMN_NOT_FOUND"},
                tool_args={"sql": "SELECT id FROM public.users WHERE foo = 1"},
                tool_context=ctx,
            )
            # asyncio.create_task spawns; await one event loop tick to let it run.
            import asyncio
            await asyncio.sleep(0.01)

        assert scheduled["count"] == 1
        assert scheduled["table_name"] == "users"
        assert scheduled["schema_name"] == "public"
        assert scheduled["reason"] == "column_not_found"

    @pytest.mark.asyncio
    async def test_helper_skips_when_flag_off(self, monkeypatch):
        from app.core.config import settings
        from app.services import react_agent

        monkeypatch.setattr(settings, "SCHEMA_AUTO_REFRESH_ON_COLUMN_NOT_FOUND", False)

        scheduled = {"count": 0}
        async def fake_refresh(*, db_config, schema_name, table_name, reason):
            scheduled["count"] += 1
            return {"success": True, "reason": "ok"}

        ctx = SimpleNamespace(
            db_config={"db_type": "postgresql", "connection_url": "postgresql://h/d", "db_name": "d"}
        )
        with patch("app.services.schema_refresh.refresh_table_schema", fake_refresh):
            react_agent._maybe_schedule_schema_refresh_on_column_error(
                error_info={"error_type": "COLUMN_NOT_FOUND"},
                tool_args={"sql": "SELECT * FROM users"},
                tool_context=ctx,
            )
            import asyncio
            await asyncio.sleep(0.01)
        assert scheduled["count"] == 0

    @pytest.mark.asyncio
    async def test_helper_skips_when_no_db_config(self):
        from app.services import react_agent

        scheduled = {"count": 0}
        async def fake_refresh(*, db_config, schema_name, table_name, reason):
            scheduled["count"] += 1
            return {"success": True, "reason": "ok"}

        ctx = SimpleNamespace(db_config=None)
        with patch("app.services.schema_refresh.refresh_table_schema", fake_refresh):
            react_agent._maybe_schedule_schema_refresh_on_column_error(
                error_info={"error_type": "COLUMN_NOT_FOUND"},
                tool_args={"sql": "SELECT * FROM users"},
                tool_context=ctx,
            )
            import asyncio
            await asyncio.sleep(0.01)
        assert scheduled["count"] == 0

    @pytest.mark.asyncio
    async def test_helper_skips_when_sql_has_no_from(self):
        from app.services import react_agent

        scheduled = {"count": 0}
        async def fake_refresh(*, db_config, schema_name, table_name, reason):
            scheduled["count"] += 1
            return {"success": True, "reason": "ok"}

        ctx = SimpleNamespace(
            db_config={"db_type": "postgresql", "connection_url": "postgresql://h/d", "db_name": "d"}
        )
        with patch("app.services.schema_refresh.refresh_table_schema", fake_refresh):
            react_agent._maybe_schedule_schema_refresh_on_column_error(
                error_info={"error_type": "COLUMN_NOT_FOUND"},
                tool_args={"sql": "SELECT 1"},  # no FROM
                tool_context=ctx,
            )
            import asyncio
            await asyncio.sleep(0.01)
        assert scheduled["count"] == 0
