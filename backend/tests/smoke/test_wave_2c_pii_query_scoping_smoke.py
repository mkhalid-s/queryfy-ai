"""
Smoke tests for SQL-aware PII redaction.

Locks in the regression fix where connection-wide OR-semantics
masked ``audit_logs.email`` just because some other table on the
same connection (``users.email``) flagged it ``is_pii=True``.

Tests cover:
  - The ``_extract_tables_from_sql`` multi-dialect parser:
    SQL FROM/JOIN, Cassandra CQL, DynamoDB PartiQL, MongoDB shell.
  - The ``_load_pii_column_set_for_query`` helper:
    SQL provided + parseable → narrows lookup; SQL absent → falls
    through to connection-wide; SQL unparseable → falls through too.
  - The integration case: query against ``audit_logs`` only, where
    ``users.email`` is flagged True and ``audit_logs.email`` is
    flagged False — the column must NOT be masked.

Run via:
    bash backend/scripts/run-tests.sh tests/smoke/test_wave_2c_pii_query_scoping_smoke.py -v
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# _extract_tables_from_sql
# ---------------------------------------------------------------------------


class TestExtractTablesFromSql:
    """Multi-dialect parser — SQL, CQL, PartiQL, MongoDB."""

    def test_simple_select_with_schema(self):
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql(
            "SELECT id, email FROM public.users WHERE id = 1"
        ) == [("public", "users")]

    def test_select_without_schema(self):
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql("SELECT * FROM customers") == [
            (None, "customers")
        ]

    def test_join_extracts_both_tables(self):
        from app.services.tools.query_tools import _extract_tables_from_sql
        result = _extract_tables_from_sql(
            "SELECT u.id, o.total FROM public.users u "
            "JOIN public.orders o ON u.id = o.customer_id"
        )
        assert ("public", "users") in result
        assert ("public", "orders") in result

    def test_quoted_identifiers_stripped(self):
        """DynamoDB PartiQL uses double quotes; MySQL backticks."""
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql('SELECT * FROM "MyTable"') == [
            (None, "MyTable")
        ]
        assert _extract_tables_from_sql("SELECT * FROM `users`") == [
            (None, "users")
        ]
        assert _extract_tables_from_sql(
            'SELECT * FROM "schema_a"."MyTable"'
        ) == [("schema_a", "MyTable")]

    def test_comments_stripped(self):
        """sqlparse normalisation should kill phantom matches in comments."""
        from app.services.tools.query_tools import _extract_tables_from_sql
        # The comment contains 'FROM phantom_table' — must NOT be picked up.
        result = _extract_tables_from_sql(
            "-- this is FROM phantom_table\nSELECT * FROM real_table"
        )
        assert ("phantom_table",) not in [(t,) for _, t in result]
        assert (None, "real_table") in result

    def test_cassandra_cql_select(self):
        """Cassandra uses SQL-shape; should work with same regex."""
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql(
            "SELECT * FROM ecommerce.orders WHERE order_id = 'x'"
        ) == [("ecommerce", "orders")]

    def test_dynamodb_partiql(self):
        """DynamoDB PartiQL with double-quoted table name."""
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql('SELECT * FROM "Orders"') == [
            (None, "Orders")
        ]

    def test_insert_into_and_update(self):
        """INTO and UPDATE keywords also referenced."""
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql(
            "INSERT INTO public.users (id, email) VALUES (1, 'a@b.com')"
        ) == [("public", "users")]
        assert _extract_tables_from_sql(
            "UPDATE customers SET status = 'active' WHERE id = 1"
        ) == [(None, "customers")]

    def test_mongodb_find(self):
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql("db.users.find({status: 'active'})") == [
            (None, "users")
        ]

    def test_mongodb_aggregate(self):
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql(
            'db.orders.aggregate([{"$match": {"status": "open"}}])'
        ) == [(None, "orders")]

    def test_returns_empty_for_no_from(self):
        from app.services.tools.query_tools import _extract_tables_from_sql
        assert _extract_tables_from_sql("SELECT 1") == []
        assert _extract_tables_from_sql("") == []

    def test_dedup_repeated_references(self):
        """A table referenced twice (e.g., self-join) yields one entry."""
        from app.services.tools.query_tools import _extract_tables_from_sql
        result = _extract_tables_from_sql(
            "SELECT a.id, b.id FROM users a JOIN users b ON a.parent_id = b.id"
        )
        assert result == [(None, "users")]

    def test_cte_referenced_alias_included_harmlessly(self):
        """
        ``WITH cte AS (...) SELECT * FROM cte`` will list ``cte`` as a
        table — that's OK; the dictionary lookup for ``cte`` will
        return nothing, contributing nothing to the PII set.
        """
        from app.services.tools.query_tools import _extract_tables_from_sql
        result = _extract_tables_from_sql(
            "WITH cte AS (SELECT * FROM real_table) SELECT * FROM cte"
        )
        names = [t for _, t in result]
        assert "real_table" in names
        assert "cte" in names  # harmless; helper falls through to heuristic


# ---------------------------------------------------------------------------
# _load_pii_column_set_for_query — narrowing behaviour
# ---------------------------------------------------------------------------


class TestLoadPiiQueryScoped:
    """The query-scoped helper closes the connection-wide false positive."""

    @pytest.mark.asyncio
    async def test_falls_back_to_connection_when_no_sql(self):
        """No SQL → connection-wide OR-semantics fallback."""
        from app.services.tools import query_tools

        called = {"connection_wide": 0, "table_scoped": 0}

        async def fake_connection_wide(db_config, columns):
            called["connection_wide"] += 1
            return {"email"}

        with patch.object(
            query_tools, "_load_pii_column_set_for_connection",
            fake_connection_wide,
        ):
            db_config = SimpleNamespace(
                db_type="postgresql",
                connection_url="postgresql://h/d",
            )
            result = await query_tools._load_pii_column_set_for_query(
                db_config, ["email", "id"], None
            )

        assert result == {"email"}
        assert called["connection_wide"] == 1

    @pytest.mark.asyncio
    async def test_falls_back_when_sql_has_no_from(self):
        """SQL provided but no FROM → connection-wide fallback."""
        from app.services.tools import query_tools

        called = {"connection_wide": 0}

        async def fake_connection_wide(db_config, columns):
            called["connection_wide"] += 1
            return {"email"}

        with patch.object(
            query_tools, "_load_pii_column_set_for_connection",
            fake_connection_wide,
        ):
            db_config = SimpleNamespace(
                db_type="postgresql",
                connection_url="postgresql://h/d",
            )
            result = await query_tools._load_pii_column_set_for_query(
                db_config, ["email"], "SELECT 1"
            )

        assert result == {"email"}
        assert called["connection_wide"] == 1

    @pytest.mark.asyncio
    async def test_narrows_to_referenced_tables(self):
        """The headline regression — SQL references audit_logs only,
        ``users.email`` flag must NOT win across tables."""
        from app.services.tools import query_tools

        # Mock the data dictionary: per-table descriptions.
        async def fake_get_descriptions(connection_hash, table_name, schema_name=None):
            if table_name == "audit_logs":
                return {
                    "email": {"is_pii": False},   # explicit override
                    "level": {"is_pii": False},
                }
            if table_name == "users":
                return {
                    "email": {"is_pii": True},    # would mask in OR-semantics
                    "name": {"is_pii": True},
                }
            return {}

        mock_dd = SimpleNamespace(
            get_table_descriptions=AsyncMock(side_effect=fake_get_descriptions),
        )
        mock_vd = SimpleNamespace(_hash_connection=lambda url: "h0123456789abcdef")

        db_config = SimpleNamespace(
            db_type="postgresql",
            connection_url="postgresql://h/d",
        )

        with patch("app.services.data_dictionary.data_dictionary", mock_dd), \
             patch("app.services.vector_db.vector_db", mock_vd):
            result = await query_tools._load_pii_column_set_for_query(
                db_config,
                columns=["email", "level"],
                sql="SELECT email, level FROM audit_logs WHERE level = 'info'",
            )

        # Lookup narrowed to audit_logs only — email is_pii=False.
        # Email must NOT be in the result. (Heuristic also doesn't
        # fire because an explicit description exists.)
        assert "email" not in result, (
            "False-positive regression: audit_logs.email "
            "(explicit is_pii=False) was masked because users.email "
            "is flagged on the same connection"
        )

    @pytest.mark.asyncio
    async def test_or_semantics_within_referenced_tables(self):
        """If SQL references multiple tables and ANY of them flags the
        column True, we DO mask (OR-semantics holds within the
        narrowed set — not across the whole connection)."""
        from app.services.tools import query_tools

        async def fake_get_descriptions(connection_hash, table_name, schema_name=None):
            if table_name == "users":
                return {"email": {"is_pii": True}}
            if table_name == "events":
                return {"email": {"is_pii": False}}
            return {}

        mock_dd = SimpleNamespace(
            get_table_descriptions=AsyncMock(side_effect=fake_get_descriptions),
        )
        mock_vd = SimpleNamespace(_hash_connection=lambda url: "h0123456789abcdef")

        db_config = SimpleNamespace(
            db_type="postgresql",
            connection_url="postgresql://h/d",
        )

        with patch("app.services.data_dictionary.data_dictionary", mock_dd), \
             patch("app.services.vector_db.vector_db", mock_vd):
            result = await query_tools._load_pii_column_set_for_query(
                db_config,
                columns=["email"],
                sql="SELECT u.email FROM users u JOIN events e ON e.user_id = u.id",
            )

        # users.email=True wins within the referenced set.
        assert "email" in result

    @pytest.mark.asyncio
    async def test_mongodb_query_narrows_to_collection(self):
        """Mongo path: db.users.find({...}) → narrow to ``users`` collection."""
        from app.services.tools import query_tools

        async def fake_get_descriptions(connection_hash, table_name, schema_name=None):
            if table_name == "users":
                return {"email": {"is_pii": False}}
            if table_name == "audit_logs":
                return {"email": {"is_pii": True}}
            return {}

        mock_dd = SimpleNamespace(
            get_table_descriptions=AsyncMock(side_effect=fake_get_descriptions),
        )
        mock_vd = SimpleNamespace(_hash_connection=lambda url: "h0123456789abcdef")

        db_config = SimpleNamespace(
            db_type="mongodb",
            connection_url="mongodb://h/db",
        )

        with patch("app.services.data_dictionary.data_dictionary", mock_dd), \
             patch("app.services.vector_db.vector_db", mock_vd):
            result = await query_tools._load_pii_column_set_for_query(
                db_config,
                columns=["email"],
                sql='db.users.find({"status": "active"})',
            )

        # users.email is_pii=False → not masked. audit_logs is irrelevant
        # because the query never references it.
        assert "email" not in result
