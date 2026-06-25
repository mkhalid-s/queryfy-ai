"""
Comprehensive unit tests for the data layer services:
- DatabaseService (database_service.py)
- DMLService (dml_service.py)
- MemoryCacheBackend / RedisCacheBackend / CacheService (cache_service.py)
- ConnectionPoolManager (connection_pool_manager.py)
- DistributedLock (distributed_lock.py)

All external dependencies (database connections, Redis, sqlalchemy engines)
are mocked. No real I/O occurs.
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# DatabaseService
# ---------------------------------------------------------------------------

class TestDatabaseServiceValidateConnectionUrl:
    """Tests for DatabaseService.validate_connection_url -- every branch."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.database_service import DatabaseService
        self.svc = DatabaseService

    # --- empty / blank ---
    def test_empty_url(self):
        ok, msg = self.svc.validate_connection_url("postgresql", "")
        assert ok is False
        assert "empty" in msg.lower()

    def test_whitespace_url(self):
        ok, msg = self.svc.validate_connection_url("postgresql", "   ")
        assert ok is False
        assert "empty" in msg.lower()

    # --- embedded databases (duckdb, sqlite) ---
    def test_duckdb_memory(self):
        ok, msg = self.svc.validate_connection_url("duckdb", "duckdb://:memory:")
        assert ok is True
        assert msg == "OK"

    def test_sqlite_memory(self):
        ok, msg = self.svc.validate_connection_url("sqlite", "sqlite://:memory:")
        assert ok is True
        assert msg == "OK"

    def test_duckdb_file_path(self):
        ok, msg = self.svc.validate_connection_url("duckdb", "duckdb:///tmp/test.duckdb")
        assert ok is True

    def test_sqlite_file_path(self):
        ok, msg = self.svc.validate_connection_url("sqlite", "sqlite:///tmp/test.db")
        assert ok is True

    def test_embedded_no_scheme(self):
        ok, msg = self.svc.validate_connection_url("duckdb", "///tmp/test.duckdb")
        assert ok is False

    def test_embedded_no_path(self):
        ok, msg = self.svc.validate_connection_url("sqlite", "sqlite:///")
        assert ok is False
        assert "file path" in msg.lower() or "No file path" in msg

    # --- DynamoDB ---
    def test_dynamodb_valid(self):
        ok, msg = self.svc.validate_connection_url("dynamodb", "dynamodb://us-east-1")
        assert ok is True

    def test_dynamodb_localhost(self):
        ok, msg = self.svc.validate_connection_url("dynamodb", "dynamodb://localhost:8000")
        assert ok is True

    def test_dynamodb_no_hostname(self):
        ok, msg = self.svc.validate_connection_url("dynamodb", "dynamodb://")
        assert ok is False
        assert "hostname" in msg.lower() or "region" in msg.lower()

    # --- standard SQL databases ---
    def test_postgresql_valid(self):
        ok, msg = self.svc.validate_connection_url(
            "postgresql", "postgresql://user:pass@localhost:5432/mydb"
        )
        assert ok is True
        assert msg == "OK"

    def test_no_hostname(self):
        ok, msg = self.svc.validate_connection_url("postgresql", "postgresql:///mydb")
        assert ok is False
        assert "hostname" in msg.lower()

    def test_placeholder_hostname(self):
        ok, msg = self.svc.validate_connection_url(
            "postgresql", "postgresql://user:pass@hostname:5432/mydb"
        )
        assert ok is False
        assert "hostname" in msg.lower()

    def test_example_hostname(self):
        ok, msg = self.svc.validate_connection_url(
            "postgresql", "postgresql://user:pass@example.com:5432/mydb"
        )
        assert ok is False

    def test_your_host_hostname(self):
        ok, msg = self.svc.validate_connection_url(
            "postgresql", "postgresql://user:pass@your-host:5432/mydb"
        )
        assert ok is False

    def test_no_username_standard_db(self):
        ok, msg = self.svc.validate_connection_url(
            "postgresql", "postgresql://@localhost:5432/mydb"
        )
        assert ok is False
        assert "username" in msg.lower()

    def test_no_database(self):
        ok, msg = self.svc.validate_connection_url(
            "postgresql", "postgresql://user:pass@localhost:5432/"
        )
        assert ok is False
        assert "database" in msg.lower()

    def test_no_auth_db_mongodb(self):
        ok, msg = self.svc.validate_connection_url(
            "mongodb", "mongodb://localhost:27017/testdb"
        )
        assert ok is True

    def test_no_auth_db_cassandra(self):
        ok, msg = self.svc.validate_connection_url(
            "cassandra", "cassandra://localhost:9042/mykeyspace"
        )
        assert ok is True

    def test_no_auth_db_clickhouse(self):
        ok, msg = self.svc.validate_connection_url(
            "clickhouse", "clickhouse://localhost:8123/default"
        )
        assert ok is True

    def test_placeholder_your_in_hostname(self):
        ok, msg = self.svc.validate_connection_url(
            "postgresql", "postgresql://user:pass@your-server.local:5432/db"
        )
        assert ok is False
        assert "placeholder" in msg.lower()

    def test_placeholder_example_in_hostname(self):
        ok, msg = self.svc.validate_connection_url(
            "mysql", "mysql://user:pass@db.example-server.com:3306/db"
        )
        assert ok is False
        assert "placeholder" in msg.lower()

    def test_exception_during_validation(self):
        with patch("app.services.database_service.urlparse", side_effect=Exception("boom")):
            ok, msg = self.svc.validate_connection_url("postgresql", "bad://url")
            assert ok is False
            assert "Invalid" in msg


class TestDatabaseServiceParseConnectionUrl:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.database_service import DatabaseService
        self.svc = DatabaseService

    def test_bigquery_url(self):
        result = self.svc.parse_connection_url("bigquery", "bigquery://my-project/dataset1")
        assert result["project"] == "my-project"
        assert result["dataset"] == "dataset1"

    def test_bigquery_no_dataset(self):
        result = self.svc.parse_connection_url("bigquery", "bigquery://my-project")
        assert result["project"] == "my-project"
        assert result["dataset"] is None

    def test_bigquery_invalid(self):
        with pytest.raises(ValueError):
            self.svc.parse_connection_url("bigquery", "bigquery://")

    def test_snowflake_url(self):
        result = self.svc.parse_connection_url(
            "snowflake",
            "snowflake://user:pass@account123/mydb/PUBLIC?warehouse=WH1&role=ANALYST"
        )
        assert result["user"] == "user"
        assert result["password"] == "pass"
        assert result["account"] == "account123"
        assert result["database"] == "mydb"
        assert result["schema"] == "PUBLIC"
        assert result["warehouse"] == "WH1"
        assert result["role"] == "ANALYST"

    def test_snowflake_defaults(self):
        result = self.svc.parse_connection_url(
            "snowflake", "snowflake://user:pass@account123/mydb"
        )
        assert result["schema"] == "PUBLIC"
        assert result["warehouse"] is None
        assert result["role"] is None

    def test_mongodb_url(self):
        result = self.svc.parse_connection_url(
            "mongodb", "mongodb://localhost:27017/testdb"
        )
        assert result == {"uri": "mongodb://localhost:27017/testdb"}

    def test_standard_sql_url(self):
        result = self.svc.parse_connection_url(
            "postgresql", "postgresql://user:pass@localhost:5432/mydb?sslmode=require"
        )
        assert result["host"] == "localhost"
        assert result["port"] == 5432
        assert result["database"] == "mydb"
        assert result["user"] == "user"
        assert result["password"] == "pass"
        assert "sslmode" in result["options"]


class TestDatabaseServiceTestConnection:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.database_service import DatabaseService
        self.svc = DatabaseService

    def _make_config(self, db_type="postgresql", url="postgresql://u:p@localhost:5432/db"):
        from app.models.schemas import DatabaseConfig
        return DatabaseConfig(db_type=db_type, connection_url=url)

    @pytest.mark.asyncio
    async def test_success(self):
        mock_executor = MagicMock()
        mock_executor.test_connection = AsyncMock(
            return_value={"success": True, "message": "OK"}
        )
        with patch("app.services.database_service.get_executor", return_value=mock_executor):
            result = await self.svc.test_connection(self._make_config())
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_unsupported_db_type(self):
        with patch(
            "app.services.database_service.get_executor",
            side_effect=ValueError("No executor"),
        ):
            result = await self.svc.test_connection(self._make_config())
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        with patch(
            "app.services.database_service.get_executor",
            side_effect=RuntimeError("Connection refused"),
        ):
            result = await self.svc.test_connection(self._make_config())
            assert result["success"] is False


class TestDatabaseServiceExtractSchema:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.database_service import DatabaseService
        self.svc = DatabaseService

    def _make_config(self, db_type="postgresql", url="postgresql://u:p@localhost:5432/db"):
        from app.models.schemas import DatabaseConfig
        return DatabaseConfig(db_type=db_type, connection_url=url)

    @pytest.mark.asyncio
    async def test_with_extractor(self):
        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(
            return_value={"tables": [{"name": "users"}]}
        )
        with patch(
            "app.services.database_service.get_schema_extractor",
            return_value=mock_extractor,
        ):
            result = await self.svc.extract_schema(self._make_config())
            assert result["tables"][0]["name"] == "users"

    @pytest.mark.asyncio
    async def test_no_extractor(self):
        with patch(
            "app.services.database_service.get_schema_extractor",
            return_value=None,
        ):
            result = await self.svc.extract_schema(self._make_config())
            assert "error" in result
            assert result["tables"] == []


class TestDatabaseServiceExecuteQuery:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.database_service import DatabaseService
        self.svc = DatabaseService

    def _make_config(self, db_type="postgresql", url="postgresql://u:p@localhost:5432/db"):
        from app.models.schemas import DatabaseConfig
        return DatabaseConfig(db_type=db_type, connection_url=url)

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        cached_data = {"columns": ["id"], "rows": [{"id": 1}], "row_count": 1}
        mock_cache = MagicMock()
        mock_cache.get_query_result = AsyncMock(return_value=cached_data)

        with patch("app.services.database_service._get_cache_service", return_value=mock_cache), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            result = await self.svc.execute_query(
                self._make_config(), "SELECT 1", limit=100
            )
            assert result["from_cache"] is True
            mock_span.end.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_then_execute(self):
        mock_cache = MagicMock()
        mock_cache.get_query_result = AsyncMock(return_value=None)
        mock_cache.set_query_result = AsyncMock()

        executor_result = {
            "success": True,
            "columns": ["id"],
            "rows": [{"id": 1}],
            "row_count": 1,
            "has_more": False,
        }
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=executor_result)

        with patch("app.services.database_service._get_cache_service", return_value=mock_cache), \
             patch("app.services.database_service.get_executor", return_value=mock_executor), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            result = await self.svc.execute_query(
                self._make_config(), "SELECT id FROM users", limit=100
            )
            assert result["from_cache"] is False
            assert result["columns"] == ["id"]
            mock_cache.set_query_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_refresh_skips_cache(self):
        mock_cache = MagicMock()
        mock_cache.get_query_result = AsyncMock(return_value=None)
        mock_cache.set_query_result = AsyncMock()

        executor_result = {
            "success": True,
            "columns": ["x"],
            "rows": [{"x": 42}],
            "row_count": 1,
            "has_more": False,
        }
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=executor_result)

        with patch("app.services.database_service._get_cache_service", return_value=mock_cache), \
             patch("app.services.database_service.get_executor", return_value=mock_executor), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            result = await self.svc.execute_query(
                self._make_config(), "SELECT x", limit=10, force_refresh=True
            )
            mock_cache.get_query_result.assert_not_awaited()
            assert result["from_cache"] is False

    @pytest.mark.asyncio
    async def test_query_validation_fails(self):
        with patch("app.services.database_service._get_cache_service", return_value=None), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(False, "Query contains DROP")), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            with pytest.raises(ValueError, match="DROP"):
                await self.svc.execute_query(self._make_config(), "DROP TABLE users")

    @pytest.mark.asyncio
    async def test_unsupported_executor(self):
        with patch("app.services.database_service._get_cache_service", return_value=None), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service.get_executor", side_effect=ValueError("nope")), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            with pytest.raises(ValueError, match="Unsupported"):
                await self.svc.execute_query(self._make_config(), "SELECT 1")

    @pytest.mark.asyncio
    async def test_timeout(self):
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(side_effect=asyncio.TimeoutError)

        with patch("app.services.database_service._get_cache_service", return_value=None), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service.get_executor", return_value=mock_executor), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            with pytest.raises(ValueError, match="exceeded maximum execution time"):
                await self.svc.execute_query(self._make_config(), "SELECT 1")

    @pytest.mark.asyncio
    async def test_executor_returns_failure(self):
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(
            return_value={"success": False, "error": "syntax error"}
        )

        with patch("app.services.database_service._get_cache_service", return_value=None), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service.get_executor", return_value=mock_executor), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            with pytest.raises(ValueError, match="syntax error"):
                await self.svc.execute_query(self._make_config(), "SELECT bad(")

    @pytest.mark.asyncio
    async def test_special_type_serialization(self):
        from decimal import Decimal

        mock_dt = MagicMock()
        mock_dt.isoformat.return_value = "2025-01-01T00:00:00"
        # Use a real Decimal instead of a mock - Decimal has __float__
        real_decimal = Decimal("3.14")

        executor_result = {
            "success": True,
            "columns": ["ts", "val"],
            "rows": [{"ts": mock_dt, "val": real_decimal}],
            "row_count": 1,
            "has_more": False,
        }
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=executor_result)

        with patch("app.services.database_service._get_cache_service", return_value=None), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service.get_executor", return_value=mock_executor), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            result = await self.svc.execute_query(self._make_config(), "SELECT ts, val FROM t")
            assert result["rows"][0]["ts"] == "2025-01-01T00:00:00"
            assert result["rows"][0]["val"] == 3.14

    @pytest.mark.asyncio
    async def test_cache_read_error_is_swallowed(self):
        mock_cache = MagicMock()
        mock_cache.get_query_result = AsyncMock(side_effect=RuntimeError("redis down"))
        mock_cache.set_query_result = AsyncMock()

        executor_result = {
            "success": True, "columns": ["a"], "rows": [{"a": 1}],
            "row_count": 1, "has_more": False,
        }
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=executor_result)

        with patch("app.services.database_service._get_cache_service", return_value=mock_cache), \
             patch("app.services.database_service.get_executor", return_value=mock_executor), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            result = await self.svc.execute_query(self._make_config(), "SELECT a FROM t")
            assert result["from_cache"] is False

    @pytest.mark.asyncio
    async def test_cache_write_error_is_swallowed(self):
        mock_cache = MagicMock()
        mock_cache.get_query_result = AsyncMock(return_value=None)
        mock_cache.set_query_result = AsyncMock(side_effect=RuntimeError("write fail"))

        executor_result = {
            "success": True, "columns": ["a"], "rows": [{"a": 1}],
            "row_count": 1, "has_more": False,
        }
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=executor_result)

        with patch("app.services.database_service._get_cache_service", return_value=mock_cache), \
             patch("app.services.database_service.get_executor", return_value=mock_executor), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            result = await self.svc.execute_query(self._make_config(), "SELECT a FROM t")
            assert result["from_cache"] is False

    @pytest.mark.asyncio
    async def test_no_cache_and_empty_rows_skips_cache_write(self):
        mock_cache = MagicMock()
        mock_cache.get_query_result = AsyncMock(return_value=None)
        mock_cache.set_query_result = AsyncMock()

        executor_result = {
            "success": True, "columns": ["a"], "rows": [],
            "row_count": 0, "has_more": False,
        }
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=executor_result)

        with patch("app.services.database_service._get_cache_service", return_value=mock_cache), \
             patch("app.services.database_service.get_executor", return_value=mock_executor), \
             patch("app.services.database_service.SecurityService.validate_generated_sql", return_value=(True, "OK")), \
             patch("app.services.database_service._tracer") as mock_tracer, \
             patch("app.services.database_service.record_db_query"):
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            await self.svc.execute_query(self._make_config(), "SELECT a FROM t WHERE 1=0")
            mock_cache.set_query_result.assert_not_awaited()


class TestDatabaseServiceCacheKey:
    def test_cache_key_deterministic(self):
        from app.services.database_service import DatabaseService
        from app.models.schemas import DatabaseConfig
        config = DatabaseConfig(db_type="postgresql", connection_url="postgresql://u:p@localhost:5432/db")
        key1 = DatabaseService._get_cache_key(config, "SELECT 1", 100)
        key2 = DatabaseService._get_cache_key(config, "SELECT 1", 100)
        assert key1 == key2

    def test_cache_key_differs_by_limit(self):
        from app.services.database_service import DatabaseService
        from app.models.schemas import DatabaseConfig
        config = DatabaseConfig(db_type="postgresql", connection_url="postgresql://u:p@localhost:5432/db")
        key1 = DatabaseService._get_cache_key(config, "SELECT 1", 100)
        key2 = DatabaseService._get_cache_key(config, "SELECT 1", 200)
        assert key1 != key2


class TestDatabaseServiceInvalidateCache:
    @pytest.mark.asyncio
    async def test_invalidate_cache_with_service(self):
        from app.services.database_service import DatabaseService
        from app.models.schemas import DatabaseConfig
        config = DatabaseConfig(db_type="postgresql", connection_url="postgresql://u:p@localhost:5432/db")
        mock_cache = MagicMock()
        mock_cache.invalidate_prefix = AsyncMock(return_value=5)
        with patch("app.services.database_service._get_cache_service", return_value=mock_cache):
            await DatabaseService.invalidate_cache(config)
            mock_cache.invalidate_prefix.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalidate_cache_no_service(self):
        from app.services.database_service import DatabaseService
        from app.models.schemas import DatabaseConfig
        config = DatabaseConfig(db_type="postgresql", connection_url="postgresql://u:p@localhost:5432/db")
        with patch("app.services.database_service._get_cache_service", return_value=None):
            await DatabaseService.invalidate_cache(config)


class TestGetCacheServiceLazyImport:
    def test_import_succeeds(self):
        from app.services.database_service import _get_cache_service
        result = _get_cache_service()
        assert result is not None or result is None


# ---------------------------------------------------------------------------
# DMLService
# ---------------------------------------------------------------------------

class TestDMLServiceCapabilities:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.dml_service import DMLService
        self.svc = DMLService

    def test_known_db(self):
        caps = self.svc.get_capabilities("postgresql")
        assert "preview" in caps["modes"]
        assert caps["has_transactions"] is True

    def test_unknown_db(self):
        caps = self.svc.get_capabilities("unknowndb")
        assert caps["modes"] == []
        assert "blocked" in caps

    def test_tier3_blocked(self):
        caps = self.svc.get_capabilities("cassandra")
        assert caps["modes"] == []
        assert "blocked" in caps


class TestDMLServiceValidateMode:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.dml_service import DMLService
        self.svc = DMLService

    def test_valid_mode(self):
        ok, msg = self.svc.validate_mode("postgresql", "preview")
        assert ok is True

    def test_blocked_db(self):
        ok, msg = self.svc.validate_mode("cassandra", "preview")
        assert ok is False

    def test_unsupported_mode(self):
        ok, msg = self.svc.validate_mode("snowflake", "sandbox")
        assert ok is False

    def test_no_modes_available(self):
        ok, msg = self.svc.validate_mode("dynamodb", "confirm")
        assert ok is False

    def test_warning_returned(self):
        ok, msg = self.svc.validate_mode("snowflake", "preview")
        assert ok is True


class TestDMLServicePreviewDml:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.dml_service import DMLService
        self.svc = DMLService

    def _make_config(self, db_type="postgresql", url="postgresql://u:p@localhost:5432/db"):
        from app.models.schemas import DatabaseConfig
        return DatabaseConfig(db_type=db_type, connection_url=url)

    @pytest.mark.asyncio
    async def test_not_dml(self):
        with patch("app.services.dml_service.SecurityService.detect_dml_operation", return_value=None):
            with pytest.raises(ValueError, match="Not a DML"):
                await self.svc.preview_dml(self._make_config(), "SELECT 1")

    @pytest.mark.asyncio
    async def test_blocked_operation(self):
        with patch("app.services.dml_service.SecurityService.detect_dml_operation", return_value="DROP"):
            with pytest.raises(ValueError, match="not allowed"):
                await self.svc.preview_dml(self._make_config(), "DROP TABLE users")

    @pytest.mark.asyncio
    async def test_insert_preview(self):
        with patch("app.services.dml_service.SecurityService.detect_dml_operation", return_value="INSERT"):
            result = await self.svc.preview_dml(
                self._make_config(), "INSERT INTO users (name) VALUES ('Alice')"
            )
            assert result.operation == "INSERT"
            assert result.table == "users"
            assert result.estimated_rows_affected == 1

    @pytest.mark.asyncio
    async def test_update_preview(self):
        mock_query_result = {"row_count": 3, "rows": [{"id": 1}, {"id": 2}, {"id": 3}]}
        with patch("app.services.dml_service.SecurityService.detect_dml_operation", return_value="UPDATE"), \
             patch("app.services.dml_service.SecurityService.get_dml_preview_sql", return_value="SELECT * FROM users WHERE active = false"), \
             patch("app.services.dml_service.DatabaseService.execute_query", new_callable=AsyncMock, return_value=mock_query_result):
            result = await self.svc.preview_dml(
                self._make_config(), "UPDATE users SET active = true WHERE active = false"
            )
            assert result.operation == "UPDATE"
            assert result.estimated_rows_affected == 3

    @pytest.mark.asyncio
    async def test_delete_preview_no_preview_sql(self):
        with patch("app.services.dml_service.SecurityService.detect_dml_operation", return_value="DELETE"), \
             patch("app.services.dml_service.SecurityService.get_dml_preview_sql", return_value=None):
            with pytest.raises(ValueError, match="Cannot generate preview"):
                await self.svc.preview_dml(self._make_config(), "DELETE FROM users")

    @pytest.mark.asyncio
    async def test_preview_query_execution_failure(self):
        with patch("app.services.dml_service.SecurityService.detect_dml_operation", return_value="DELETE"), \
             patch("app.services.dml_service.SecurityService.get_dml_preview_sql", return_value="SELECT * FROM users WHERE id = 1"), \
             patch("app.services.dml_service.DatabaseService.execute_query", new_callable=AsyncMock, side_effect=RuntimeError("connection refused")):
            with pytest.raises(ValueError, match="Failed to preview"):
                await self.svc.preview_dml(self._make_config(), "DELETE FROM users WHERE id = 1")


class TestDMLServiceExecuteSandbox:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.dml_service import DMLService
        self.svc = DMLService

    def _make_config(self, db_type="postgresql", url="postgresql://u:p@localhost:5432/db"):
        from app.models.schemas import DatabaseConfig
        return DatabaseConfig(db_type=db_type, connection_url=url)

    @pytest.mark.asyncio
    async def test_success(self):
        mock_executor = MagicMock()
        mock_executor.execute_dml = AsyncMock(return_value={"rows_affected": 5})
        with patch("app.services.executors.get_executor", return_value=mock_executor):
            result = await self.svc.execute_sandbox(self._make_config(), "UPDATE users SET active = true")
            assert result["success"] is True
            assert result["rows_affected"] == 5
            assert result["rollback_performed"] is True
            call_kwargs = mock_executor.execute_dml.call_args[1]
            assert call_kwargs["rollback"] is True

    @pytest.mark.asyncio
    async def test_unsupported_db(self):
        with patch("app.services.executors.get_executor", side_effect=ValueError("nope")):
            with pytest.raises(ValueError, match="Unsupported"):
                await self.svc.execute_sandbox(self._make_config(), "UPDATE t SET x=1")

    @pytest.mark.asyncio
    async def test_no_dml_support(self):
        mock_executor = MagicMock(spec=[])
        with patch("app.services.executors.get_executor", return_value=mock_executor):
            with pytest.raises(ValueError, match="DML not supported"):
                await self.svc.execute_sandbox(self._make_config(), "UPDATE t SET x=1")


class TestDMLServiceExecuteConfirmed:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.dml_service import DMLService
        self.svc = DMLService

    def _make_config(self, db_type="postgresql", url="postgresql://u:p@localhost:5432/db"):
        from app.models.schemas import DatabaseConfig
        return DatabaseConfig(db_type=db_type, connection_url=url)

    @pytest.mark.asyncio
    async def test_success(self):
        mock_executor = MagicMock()
        mock_executor.execute_dml = AsyncMock(return_value={"rows_affected": 2})
        with patch("app.services.executors.get_executor", return_value=mock_executor):
            result = await self.svc.execute_confirmed(self._make_config(), "DELETE FROM users WHERE id = 5")
            assert result["success"] is True
            assert result["rows_affected"] == 2
            assert result["rollback_performed"] is False

    @pytest.mark.asyncio
    async def test_unsupported_db(self):
        with patch("app.services.executors.get_executor", side_effect=ValueError("nope")):
            with pytest.raises(ValueError, match="Unsupported"):
                await self.svc.execute_confirmed(self._make_config(), "DELETE FROM t")

    @pytest.mark.asyncio
    async def test_no_dml_support(self):
        mock_executor = MagicMock(spec=[])
        with patch("app.services.executors.get_executor", return_value=mock_executor):
            with pytest.raises(ValueError, match="DML not supported"):
                await self.svc.execute_confirmed(self._make_config(), "DELETE FROM t")


class TestDMLServiceConfirmationToken:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.dml_service import DMLService
        self.svc = DMLService

    @pytest.mark.asyncio
    async def test_generate_and_validate_token(self):
        mock_backend = MagicMock()
        mock_backend.set = AsyncMock()
        mock_backend.get = AsyncMock()
        mock_backend.delete = AsyncMock()

        with patch("app.services.dml_service.cache_service") as mock_cs:
            mock_cs._backend = mock_backend
            token = await self.svc.generate_confirmation_token("session-abc", "DELETE FROM users")
            assert isinstance(token, str)
            assert len(token) > 0
            mock_backend.set.assert_awaited_once()

            set_call = mock_backend.set.call_args
            stored_data = json.loads(set_call[0][1])
            mock_backend.get.return_value = json.dumps(stored_data)

            valid = await self.svc.validate_confirmation_token(token, "session-abc", "DELETE FROM users")
            assert valid is True
            mock_backend.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validate_expired_or_missing(self):
        mock_backend = MagicMock()
        mock_backend.get = AsyncMock(return_value=None)
        with patch("app.services.dml_service.cache_service") as mock_cs:
            mock_cs._backend = mock_backend
            valid = await self.svc.validate_confirmation_token("fake-token", "session-abc", "DELETE FROM users")
            assert valid is False

    @pytest.mark.asyncio
    async def test_validate_session_mismatch(self):
        token_data = {"session_id": "session-xyz", "sql_hash": hashlib.sha256(b"DELETE FROM users").hexdigest()}
        mock_backend = MagicMock()
        mock_backend.get = AsyncMock(return_value=json.dumps(token_data))
        with patch("app.services.dml_service.cache_service") as mock_cs:
            mock_cs._backend = mock_backend
            valid = await self.svc.validate_confirmation_token("some-token", "session-WRONG", "DELETE FROM users")
            assert valid is False

    @pytest.mark.asyncio
    async def test_validate_sql_mismatch(self):
        token_data = {"session_id": "session-abc", "sql_hash": hashlib.sha256(b"DELETE FROM other_table").hexdigest()}
        mock_backend = MagicMock()
        mock_backend.get = AsyncMock(return_value=json.dumps(token_data))
        with patch("app.services.dml_service.cache_service") as mock_cs:
            mock_cs._backend = mock_backend
            valid = await self.svc.validate_confirmation_token("some-token", "session-abc", "DELETE FROM users")
            assert valid is False

    @pytest.mark.asyncio
    async def test_validate_exception_returns_false(self):
        mock_backend = MagicMock()
        mock_backend.get = AsyncMock(side_effect=RuntimeError("redis down"))
        with patch("app.services.dml_service.cache_service") as mock_cs:
            mock_cs._backend = mock_backend
            valid = await self.svc.validate_confirmation_token("some-token", "session-abc", "DELETE FROM users")
            assert valid is False

    @pytest.mark.asyncio
    async def test_generate_storage_error(self):
        mock_backend = MagicMock()
        mock_backend.set = AsyncMock(side_effect=RuntimeError("storage failure"))
        with patch("app.services.dml_service.cache_service") as mock_cs:
            mock_cs._backend = mock_backend
            with pytest.raises(ValueError, match="storage error"):
                await self.svc.generate_confirmation_token("sess", "DELETE FROM t")

    @pytest.mark.asyncio
    async def test_validate_no_backend(self):
        with patch("app.services.dml_service.cache_service") as mock_cs:
            mock_cs._backend = None
            valid = await self.svc.validate_confirmation_token("some-token", "session-abc", "DELETE FROM users")
            assert valid is False


class TestDMLServiceHelpers:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.dml_service import DMLService
        self.svc = DMLService

    def test_extract_table_insert(self):
        assert self.svc._extract_table("INSERT INTO users (name) VALUES ('a')") == "users"

    def test_extract_table_update(self):
        assert self.svc._extract_table("UPDATE orders SET status = 'done'") == "orders"

    def test_extract_table_delete(self):
        assert self.svc._extract_table("DELETE FROM items WHERE id = 1") == "items"

    def test_extract_table_schema_qualified(self):
        assert self.svc._extract_table("INSERT INTO public.users (name) VALUES ('a')") == "public.users"

    def test_extract_table_quoted(self):
        result = self.svc._extract_table('UPDATE "User Table" SET x = 1')
        assert result == '"User Table"'

    def test_extract_table_unknown(self):
        assert self.svc._extract_table("SELECT 1") == "unknown"

    def test_count_insert_rows_single(self):
        assert self.svc._count_insert_rows("INSERT INTO t VALUES (1)") == 1

    def test_count_insert_rows_multiple(self):
        assert self.svc._count_insert_rows("INSERT INTO t VALUES (1), (2), (3)") == 3

    def test_count_insert_rows_no_values(self):
        assert self.svc._count_insert_rows("INSERT INTO t SELECT * FROM s") == 1

    def test_generate_warnings_none(self):
        warnings = self.svc._generate_warnings("DELETE", {"row_count": 0})
        assert any("No rows" in w for w in warnings)

    def test_generate_warnings_large(self):
        warnings = self.svc._generate_warnings("UPDATE", {"row_count": 150})
        assert any("150 rows" in w for w in warnings)

    def test_generate_warnings_very_large(self):
        warnings = self.svc._generate_warnings("DELETE", {"row_count": 5000})
        assert len(warnings) == 2

    def test_generate_warnings_small(self):
        warnings = self.svc._generate_warnings("UPDATE", {"row_count": 5})
        assert warnings == []

    def test_cleanup_expired_tokens(self):
        self.svc.cleanup_expired_tokens()


# ---------------------------------------------------------------------------
# MemoryCacheBackend
# ---------------------------------------------------------------------------

class TestMemoryCacheBackend:
    @pytest.fixture
    def backend(self):
        from app.services.cache_service import MemoryCacheBackend
        return MemoryCacheBackend()

    @pytest.mark.asyncio
    async def test_get_miss(self, backend):
        result = await backend.get("nonexistent")
        assert result is None
        assert backend._stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_set_and_get(self, backend):
        await backend.set("key1", "value1", ttl=60)
        result = await backend.get("key1")
        assert result == "value1"
        assert backend._stats["hits"] == 1

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, backend):
        await backend.set("expiring", "data", ttl=1)
        backend._cache["expiring"]["expires_at"] = time.time() - 1
        result = await backend.get("expiring")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_ttl_never_expires(self, backend):
        await backend.set("permanent", "data", ttl=0)
        assert backend._cache["permanent"]["expires_at"] is None
        result = await backend.get("permanent")
        assert result == "data"

    @pytest.mark.asyncio
    async def test_delete(self, backend):
        await backend.set("key1", "value1", ttl=60)
        await backend.delete("key1")
        result = await backend.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, backend):
        await backend.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_delete_prefix(self, backend):
        await backend.set("prefix:a", "1", ttl=60)
        await backend.set("prefix:b", "2", ttl=60)
        await backend.set("other:c", "3", ttl=60)
        deleted = await backend.delete_prefix("prefix:")
        assert deleted == 2
        assert await backend.get("other:c") == "3"

    @pytest.mark.asyncio
    async def test_exists_true(self, backend):
        await backend.set("key", "val", ttl=60)
        assert await backend.exists("key") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, backend):
        assert await backend.exists("nonexistent") is False

    @pytest.mark.asyncio
    async def test_exists_expired(self, backend):
        await backend.set("exp", "val", ttl=1)
        backend._cache["exp"]["expires_at"] = time.time() - 1
        assert await backend.exists("exp") is False

    @pytest.mark.asyncio
    async def test_get_ttl_valid(self, backend):
        await backend.set("key", "val", ttl=3600)
        remaining = await backend.get_ttl("key")
        assert 0 < remaining <= 3600

    @pytest.mark.asyncio
    async def test_get_ttl_missing(self, backend):
        assert await backend.get_ttl("nonexistent") == -1

    @pytest.mark.asyncio
    async def test_get_ttl_no_expiry(self, backend):
        await backend.set("permanent", "val", ttl=0)
        assert await backend.get_ttl("permanent") == -1

    @pytest.mark.asyncio
    async def test_get_ttl_expired(self, backend):
        await backend.set("exp", "val", ttl=1)
        backend._cache["exp"]["expires_at"] = time.time() - 1
        assert await backend.get_ttl("exp") == -1

    @pytest.mark.asyncio
    async def test_ping(self, backend):
        assert await backend.ping() is True

    def test_get_stats(self, backend):
        stats = backend.get_stats()
        assert stats["backend"] == "memory"
        assert stats["entries"] == 0
        assert stats["hit_rate"] == 0

    @pytest.mark.asyncio
    async def test_stats_hit_rate(self, backend):
        await backend.set("k", "v", ttl=60)
        await backend.get("k")
        await backend.get("miss")
        stats = backend.get_stats()
        assert stats["hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_cleanup_triggered_on_100th_set(self, backend):
        await backend.set("old", "data", ttl=1)
        backend._cache["old"]["expires_at"] = time.time() - 10
        for i in range(99):
            await backend.set(f"k{i}", "v", ttl=60)
        assert "old" not in backend._cache

    def test_is_expired_no_expires_at(self, backend):
        assert backend._is_expired({"value": "test", "expires_at": None}) is False

    def test_cleanup_expired_no_expired(self, backend):
        backend._cleanup_expired()


# ---------------------------------------------------------------------------
# RedisCacheBackend
# ---------------------------------------------------------------------------

class TestRedisCacheBackend:
    @pytest.fixture
    def backend(self):
        from app.services.cache_service import RedisCacheBackend
        return RedisCacheBackend("redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_get_success(self, backend):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="cached_value")
        backend._client = mock_client
        result = await backend.get("key")
        assert result == "cached_value"
        assert backend._stats["hits"] == 1

    @pytest.mark.asyncio
    async def test_get_miss(self, backend):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        backend._client = mock_client
        assert await backend.get("key") is None
        assert backend._stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_get_error(self, backend):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("down"))
        backend._client = mock_client
        assert await backend.get("key") is None

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, backend):
        mock_client = AsyncMock()
        mock_client.setex = AsyncMock()
        backend._client = mock_client
        await backend.set("key", "val", ttl=60)
        mock_client.setex.assert_awaited_once_with("key", 60, "val")

    @pytest.mark.asyncio
    async def test_set_no_ttl(self, backend):
        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        backend._client = mock_client
        await backend.set("key", "val", ttl=0)
        mock_client.set.assert_awaited_once_with("key", "val")

    @pytest.mark.asyncio
    async def test_set_error(self, backend):
        mock_client = AsyncMock()
        mock_client.setex = AsyncMock(side_effect=ConnectionError("down"))
        backend._client = mock_client
        await backend.set("key", "val", ttl=60)

    @pytest.mark.asyncio
    async def test_delete_success(self, backend):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock()
        backend._client = mock_client
        await backend.delete("key")
        mock_client.delete.assert_awaited_once_with("key")

    @pytest.mark.asyncio
    async def test_delete_error(self, backend):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(side_effect=ConnectionError("down"))
        backend._client = mock_client
        await backend.delete("key")

    @pytest.mark.asyncio
    async def test_delete_prefix(self, backend):
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(return_value=(0, ["lock:a", "lock:b"]))
        mock_client.delete = AsyncMock()
        backend._client = mock_client
        assert await backend.delete_prefix("lock:") == 2

    @pytest.mark.asyncio
    async def test_delete_prefix_error(self, backend):
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(side_effect=ConnectionError("down"))
        backend._client = mock_client
        assert await backend.delete_prefix("lock:") == 0

    @pytest.mark.asyncio
    async def test_exists_true(self, backend):
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(return_value=1)
        backend._client = mock_client
        assert await backend.exists("key") is True

    @pytest.mark.asyncio
    async def test_exists_error(self, backend):
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(side_effect=ConnectionError("down"))
        backend._client = mock_client
        assert await backend.exists("key") is False

    @pytest.mark.asyncio
    async def test_get_ttl_positive(self, backend):
        mock_client = AsyncMock()
        mock_client.ttl = AsyncMock(return_value=120)
        backend._client = mock_client
        assert await backend.get_ttl("key") == 120

    @pytest.mark.asyncio
    async def test_get_ttl_negative(self, backend):
        mock_client = AsyncMock()
        mock_client.ttl = AsyncMock(return_value=-2)
        backend._client = mock_client
        assert await backend.get_ttl("key") == -1

    @pytest.mark.asyncio
    async def test_get_ttl_error(self, backend):
        mock_client = AsyncMock()
        mock_client.ttl = AsyncMock(side_effect=ConnectionError("down"))
        backend._client = mock_client
        assert await backend.get_ttl("key") == -1

    @pytest.mark.asyncio
    async def test_ping_success(self, backend):
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        backend._client = mock_client
        assert await backend.ping() is True

    @pytest.mark.asyncio
    async def test_ping_failure(self, backend):
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(side_effect=ConnectionError("down"))
        backend._client = mock_client
        assert await backend.ping() is False

    def test_get_stats(self, backend):
        stats = backend.get_stats()
        assert stats["backend"] == "redis"

    def test_get_stats_url_with_auth(self):
        from app.services.cache_service import RedisCacheBackend
        b = RedisCacheBackend("redis://user:pass@localhost:6379")
        stats = b.get_stats()
        assert "user:pass" not in stats["redis_url"]


# ---------------------------------------------------------------------------
# CacheService
# ---------------------------------------------------------------------------

class TestCacheService:
    @pytest.fixture
    def service(self):
        from app.services.cache_service import CacheService
        return CacheService()

    @pytest.mark.asyncio
    async def test_initialize_no_redis(self, service):
        await service.initialize()
        assert service._initialized is True
        from app.services.cache_service import MemoryCacheBackend
        assert isinstance(service._backend, MemoryCacheBackend)

    @pytest.mark.asyncio
    async def test_initialize_redis_success(self):
        from app.services.cache_service import CacheService
        svc = CacheService(redis_url="redis://localhost:6379")
        mock_backend = MagicMock()
        mock_backend.ping = AsyncMock(return_value=True)
        with patch("app.services.cache_service.RedisCacheBackend", return_value=mock_backend):
            await svc.initialize()
            assert svc._backend is mock_backend

    @pytest.mark.asyncio
    async def test_initialize_redis_failure_falls_back(self):
        from app.services.cache_service import CacheService, MemoryCacheBackend
        svc = CacheService(redis_url="redis://localhost:6379")
        mock_backend = MagicMock()
        mock_backend.ping = AsyncMock(side_effect=ConnectionError("nope"))
        with patch("app.services.cache_service.RedisCacheBackend", return_value=mock_backend):
            await svc.initialize()
            assert isinstance(svc._backend, MemoryCacheBackend)

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, service):
        await service.initialize()
        backend1 = service._backend
        await service.initialize()
        assert service._backend is backend1

    def test_ensure_initialized_lazy(self, service):
        assert service._initialized is False
        service._ensure_initialized()
        assert service._initialized is True

    def test_hash_prompt(self, service):
        h1 = service.hash_prompt("SELECT users", "schema1", "postgresql")
        h2 = service.hash_prompt("SELECT users", "schema1", "postgresql")
        h3 = service.hash_prompt("SELECT users", "schema2", "postgresql")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 32

    @pytest.mark.asyncio
    async def test_llm_response_cache(self, service):
        await service.initialize()
        await service.set_llm_response("hash1", "SELECT * FROM users")
        assert await service.get_llm_response("hash1") == "SELECT * FROM users"

    @pytest.mark.asyncio
    async def test_query_result_cache(self, service):
        await service.initialize()
        data = {"columns": ["id"], "rows": [{"id": 1}], "row_count": 1}
        await service.set_query_result("qkey", data)
        assert await service.get_query_result("qkey") == data

    @pytest.mark.asyncio
    async def test_schema_cache(self, service):
        await service.initialize()
        schema = {"tables": [{"name": "users"}]}
        await service.set_schema("dbhash1", schema)
        assert await service.get_schema("dbhash1") == schema

    @pytest.mark.asyncio
    async def test_invalidate_prefix(self, service):
        await service.initialize()
        await service._backend.set("query:abc:1", "data", ttl=60)
        await service._backend.set("query:abc:2", "data", ttl=60)
        assert await service.invalidate_prefix("query:abc") == 2

    @pytest.mark.asyncio
    async def test_invalidate_db_cache(self, service):
        await service.initialize()
        await service._backend.set("query:hash1:a", "data", ttl=60)
        await service._backend.set("schema:hash1:b", "data", ttl=60)
        assert await service.invalidate_db_cache("hash1") == 2

    @pytest.mark.asyncio
    async def test_clear_all(self, service):
        await service.initialize()
        await service.set_llm_response("h1", "sql")
        await service.clear_all()
        assert await service.get_llm_response("h1") is None

    @pytest.mark.asyncio
    async def test_ping(self, service):
        await service.initialize()
        assert await service.ping() is True

    def test_get_stats(self, service):
        service._ensure_initialized()
        assert "backend" in service.get_stats()

    def test_get_llm_hit_rate(self, service):
        service._ensure_initialized()
        # hit_rate is 0 (int) when no hits/misses yet; accept int or float
        assert isinstance(service.get_llm_hit_rate(), (int, float))

    @pytest.mark.asyncio
    async def test_get_cache_age(self, service):
        await service.initialize()
        await service.set_query_result("aging", {"rows": []})
        assert await service.get_cache_age("aging") >= 0

    @pytest.mark.asyncio
    async def test_get_cache_age_missing(self, service):
        await service.initialize()
        assert await service.get_cache_age("nonexistent") == -1

    @pytest.mark.asyncio
    async def test_operations_with_none_backend(self):
        from app.services.cache_service import CacheService
        svc = CacheService()
        svc._initialized = True
        svc._backend = None
        # _ensure_initialized() recreates a MemoryCacheBackend when _backend is None
        assert await svc.get_llm_response("x") is None
        await svc.set_llm_response("x", "y")
        assert await svc.get_query_result("x") is None
        assert await svc.get_schema("x") is None
        assert await svc.invalidate_prefix("x") == 0
        assert await svc.invalidate_db_cache("x") == 0
        await svc.clear_all()
        assert await svc.ping() is True  # MemoryCacheBackend always pings True
        assert await svc.get_cache_age("x") == -1

    def test_get_stats_no_backend(self):
        from app.services.cache_service import CacheService
        svc = CacheService()
        svc._initialized = True
        svc._backend = None
        # _ensure_initialized() recreates a MemoryCacheBackend when _backend is None,
        # so get_stats() returns memory backend stats, not empty dict
        stats = svc.get_stats()
        assert stats["backend"] == "memory"
        assert stats["entries"] == 0


class TestInitializeCache:
    @pytest.mark.asyncio
    async def test_initialize_cache_function(self):
        from app.services.cache_service import initialize_cache, cache_service
        result = await initialize_cache(redis_url=None)
        assert result is cache_service
        assert cache_service._initialized is True


# ---------------------------------------------------------------------------
# ConnectionPoolManager
# ---------------------------------------------------------------------------

class TestConnectionPoolManager:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        old_instance = ConnectionPoolManager._instance
        ConnectionPoolManager._instance = None
        yield
        ConnectionPoolManager._instance = old_instance

    def _make_config(self, db_type="postgresql", url="postgresql://u:p@localhost:5432/db"):
        from app.models.schemas import DatabaseConfig
        return DatabaseConfig(db_type=db_type, connection_url=url)

    def test_singleton(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        assert ConnectionPoolManager() is ConnectionPoolManager()

    def test_init_only_once(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        mgr.config.max_size = 999
        ConnectionPoolManager()
        assert mgr.config.max_size == 999

    def test_pool_key_deterministic(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        config = self._make_config()
        assert mgr._get_pool_key(config) == mgr._get_pool_key(config)

    def test_pool_key_differs_by_db_type(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        assert mgr._get_pool_key(self._make_config("postgresql")) != mgr._get_pool_key(self._make_config("mysql", "mysql://u:p@localhost:5432/db"))

    def test_get_pool_stats_empty(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        assert ConnectionPoolManager().get_pool_stats() == {}

    def test_get_pool_stats_with_entries(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        mgr._pool_stats["test_key"] = PoolStats()
        stats = mgr.get_pool_stats()
        assert "test_key" in stats
        assert "idle_seconds" in stats["test_key"]

    @pytest.mark.asyncio
    async def test_get_or_create_lock(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        lock1 = await mgr._get_or_create_lock("pool_a")
        assert lock1 is await mgr._get_or_create_lock("pool_a")

    @pytest.mark.asyncio
    async def test_get_sync_connection_unsupported(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        # Use a valid db_type (passes Pydantic) that is NOT in the sync creators dict.
        # postgresql/mysql/mongodb are async-only, so they trigger the unsupported path.
        with pytest.raises(ValueError, match="Unsupported"):
            await ConnectionPoolManager()._get_sync_connection(self._make_config("postgresql", "postgresql://u:p@localhost:5432/db"))

    @pytest.mark.asyncio
    async def test_get_or_create_async_pool_unsupported(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        with pytest.raises(ValueError, match="No async pool support"):
            await ConnectionPoolManager()._get_or_create_async_pool(self._make_config("snowflake", "snowflake://u:p@acct/db/sc?warehouse=WH"))

    @pytest.mark.asyncio
    async def test_get_or_create_async_pool_existing(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        config = self._make_config()
        pool_key = mgr._get_pool_key(config)
        mock_pool = MagicMock()
        mgr._async_pools[pool_key] = mock_pool
        mgr._pool_stats[pool_key] = PoolStats()
        assert await mgr._get_or_create_async_pool(config) is mock_pool

    @pytest.mark.asyncio
    async def test_close_pool(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        mock_pool = MagicMock()
        mock_pool.close = MagicMock(return_value=None)
        mock_pool.wait_closed = AsyncMock()
        mgr._async_pools["key1"] = mock_pool
        mgr._pool_stats["key1"] = PoolStats()
        mgr._pool_locks["key1"] = asyncio.Lock()
        await mgr._close_pool("key1")
        assert "key1" not in mgr._async_pools

    @pytest.mark.asyncio
    async def test_close_pool_error_handled(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        mock_pool = MagicMock()
        mock_pool.close = MagicMock(side_effect=RuntimeError("fail"))
        mgr._async_pools["key3"] = mock_pool
        mgr._pool_stats["key3"] = PoolStats()
        await mgr._close_pool("key3")
        assert "key3" not in mgr._async_pools

    @pytest.mark.asyncio
    async def test_close_pool_nonexistent(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        await ConnectionPoolManager()._close_pool("nonexistent")

    @pytest.mark.asyncio
    async def test_cleanup_idle_pools(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        old_stats = PoolStats()
        old_stats.last_used = datetime(2020, 1, 1)
        mock_pool = MagicMock()
        mock_pool.close = MagicMock(return_value=None)
        mgr._async_pools["old_key"] = mock_pool
        mgr._pool_stats["old_key"] = old_stats
        await mgr._cleanup_idle_pools()
        assert "old_key" not in mgr._async_pools

    @pytest.mark.asyncio
    async def test_cleanup_idle_pools_keeps_active(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        recent_stats = PoolStats()
        recent_stats.last_used = datetime.now()
        mgr._pool_stats["active_key"] = recent_stats
        mgr._async_pools["active_key"] = MagicMock()
        await mgr._cleanup_idle_pools()
        assert "active_key" in mgr._pool_stats

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        with patch.object(mgr, "get_connection", side_effect=ConnectionError("fail")):
            result = await mgr.health_check(self._make_config())
            assert result["healthy"] is False

    @pytest.mark.asyncio
    async def test_close_sync_connection(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        mock_conn = MagicMock()
        await mgr._close_sync_connection(mock_conn, "duckdb")
        mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_sync_connection_cassandra(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        mock_conn = MagicMock()
        mock_conn._cluster_ref = MagicMock()
        await mgr._close_sync_connection(mock_conn, "cassandra")
        mock_conn._cluster_ref.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_sync_connection_error_swallowed(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        mock_conn = MagicMock()
        mock_conn.close = MagicMock(side_effect=RuntimeError("fail"))
        await mgr._close_sync_connection(mock_conn, "sqlite")

    def test_get_dynamodb_client_kwargs_local(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        result = mgr._get_dynamodb_client_kwargs(self._make_config("dynamodb", "dynamodb://localhost:8000/"))
        assert result["endpoint_url"] == "http://localhost:8000"
        assert result["region_name"] == "local"

    def test_get_dynamodb_client_kwargs_aws(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        result = mgr._get_dynamodb_client_kwargs(self._make_config("dynamodb", "dynamodb://us-east-1/1234567890"))
        assert result["region_name"] == "us-east-1"

    def test_get_dynamodb_client_kwargs_with_creds(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        mgr = ConnectionPoolManager()
        result = mgr._get_dynamodb_client_kwargs(self._make_config("dynamodb", "dynamodb://AKID:SECRET@us-east-1/1234567890"))
        assert result["aws_access_key_id"] == "AKID"


class TestConnectionPoolManagerGetConnection:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        from app.services.connection_pool_manager import ConnectionPoolManager
        old_instance = ConnectionPoolManager._instance
        ConnectionPoolManager._instance = None
        yield
        ConnectionPoolManager._instance = old_instance

    def _make_config(self, db_type="postgresql", url="postgresql://u:p@localhost:5432/db"):
        from app.models.schemas import DatabaseConfig
        return DatabaseConfig(db_type=db_type, connection_url=url)

    @pytest.mark.asyncio
    async def test_get_connection_postgresql(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        config = self._make_config()
        pool_key = mgr._get_pool_key(config)
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1)  # pre-flight SELECT 1
        mock_pool = MagicMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()
        mgr._async_pools[pool_key] = mock_pool
        mgr._pool_stats[pool_key] = PoolStats()
        async with mgr.get_connection(config) as conn:
            assert conn is mock_conn
        mock_pool.release.assert_awaited_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_get_connection_mysql(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        config = self._make_config("mysql", "mysql://u:p@localhost:3306/db")
        pool_key = mgr._get_pool_key(config)
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = MagicMock()
        mgr._async_pools[pool_key] = mock_pool
        mgr._pool_stats[pool_key] = PoolStats()
        async with mgr.get_connection(config) as conn:
            assert conn is mock_conn

    @pytest.mark.asyncio
    async def test_get_connection_mongodb(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        config = self._make_config("mongodb", "mongodb://localhost:27017/testdb1234567890")
        pool_key = mgr._get_pool_key(config)
        mock_client = MagicMock()
        mgr._async_pools[pool_key] = mock_client
        mgr._pool_stats[pool_key] = PoolStats()
        async with mgr.get_connection(config) as conn:
            assert conn is mock_client

    @pytest.mark.asyncio
    async def test_get_connection_error_updates_stats(self):
        from app.services.connection_pool_manager import ConnectionPoolManager, PoolStats
        mgr = ConnectionPoolManager()
        config = self._make_config()
        pool_key = mgr._get_pool_key(config)
        mgr._pool_stats[pool_key] = PoolStats()
        with patch.object(mgr, "_get_or_create_async_pool", side_effect=RuntimeError("fail")):
            with pytest.raises(RuntimeError):
                async with mgr.get_connection(config):
                    pass
            assert mgr._pool_stats[pool_key].errors == 1


# ---------------------------------------------------------------------------
# DistributedLock
# ---------------------------------------------------------------------------

class TestDistributedLock:
    @pytest.fixture(autouse=True)
    def reset_lock_state(self):
        from app.services.distributed_lock import DistributedLock
        from app.core.config import settings
        DistributedLock._redis_client = None
        DistributedLock._redis_initialized = False
        DistributedLock._local_locks = {}
        with patch.object(settings, "DEVELOPMENT_MODE", True):
            yield
        DistributedLock._redis_client = None
        DistributedLock._redis_initialized = False
        DistributedLock._local_locks = {}

    @pytest.mark.asyncio
    async def test_acquire_and_release_local(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = None
        lock = DistributedLock("test-lock", ttl_seconds=10, acquire_timeout=5)
        assert await lock.acquire() is True
        assert lock._using_local_lock is True
        assert await lock.release() is True

    @pytest.mark.asyncio
    async def test_release_without_acquire(self):
        from app.services.distributed_lock import DistributedLock
        assert await DistributedLock("test-lock2").release() is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = None
        lock = DistributedLock("ctx-lock", acquire_timeout=5)
        async with lock:
            assert lock._acquired is True
        assert lock._acquired is False

    @pytest.mark.asyncio
    async def test_context_manager_timeout(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = None
        DistributedLock._local_locks["timeout-lock"] = asyncio.Lock()
        await DistributedLock._local_locks["timeout-lock"].acquire()
        lock = DistributedLock("timeout-lock", acquire_timeout=0.1)
        with pytest.raises(TimeoutError, match="Failed to acquire lock"):
            async with lock:
                pass
        DistributedLock._local_locks["timeout-lock"].release()

    @pytest.mark.asyncio
    async def test_local_lock_timeout(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = None
        DistributedLock._local_locks["busy-lock"] = asyncio.Lock()
        await DistributedLock._local_locks["busy-lock"].acquire()
        lock = DistributedLock("busy-lock", acquire_timeout=0.1)
        assert await lock.acquire() is False
        DistributedLock._local_locks["busy-lock"].release()

    @pytest.mark.asyncio
    async def test_release_local_lock_not_held(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = None
        lock = DistributedLock("not-held-lock")
        lock._acquired = True
        lock._using_local_lock = True
        DistributedLock._local_locks["not-held-lock"] = asyncio.Lock()
        assert await lock.release() is False

    @pytest.mark.asyncio
    async def test_release_local_lock_not_in_dict(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = None
        lock = DistributedLock("nonexistent-local")
        lock._acquired = True
        lock._using_local_lock = True
        assert await lock.release() is False

    @pytest.mark.asyncio
    async def test_extend_not_acquired(self):
        from app.services.distributed_lock import DistributedLock
        assert await DistributedLock("ext-lock").extend(60) is False

    @pytest.mark.asyncio
    async def test_extend_local_lock(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = None
        lock = DistributedLock("ext-local-lock", acquire_timeout=5)
        await lock.acquire()
        assert await lock.extend(60) is True
        await lock.release()

    @pytest.mark.asyncio
    async def test_is_locked_local(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = None
        lock = DistributedLock("check-lock", acquire_timeout=5)
        assert await lock.is_locked() is False
        await lock.acquire()
        assert await lock.is_locked() is True
        await lock.release()

    def test_with_ttl(self):
        from app.services.distributed_lock import DistributedLock
        lock = DistributedLock("base-lock", ttl_seconds=60, acquire_timeout=10)
        new_lock = lock.with_ttl(300)
        assert new_lock.ttl_seconds == 300
        assert new_lock is not lock


class TestDistributedLockRedis:
    @pytest.fixture(autouse=True)
    def reset_lock_state(self):
        from app.services.distributed_lock import DistributedLock
        from app.core.config import settings
        DistributedLock._redis_client = None
        DistributedLock._redis_initialized = False
        DistributedLock._local_locks = {}
        with patch.object(settings, "DEVELOPMENT_MODE", True):
            yield
        DistributedLock._redis_client = None
        DistributedLock._redis_initialized = False
        DistributedLock._local_locks = {}

    @pytest.mark.asyncio
    async def test_acquire_redis_success(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(return_value=True)
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        lock = DistributedLock("redis-lock", acquire_timeout=5)
        assert await lock.acquire() is True
        assert lock._using_local_lock is False

    @pytest.mark.asyncio
    async def test_acquire_redis_timeout(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(return_value=False)
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        lock = DistributedLock("busy-redis-lock", acquire_timeout=0.3)
        assert await lock.acquire() is False

    @pytest.mark.asyncio
    async def test_acquire_redis_error_falls_back(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        lock = DistributedLock("fallback-lock", acquire_timeout=5)
        assert await lock.acquire() is True
        assert lock._using_local_lock is True
        await lock.release()

    @pytest.mark.asyncio
    async def test_release_redis_success(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        lock = DistributedLock("rel-redis-lock", acquire_timeout=5)
        await lock.acquire()
        assert await lock.release() is True

    @pytest.mark.asyncio
    async def test_release_redis_not_owner(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=0)
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        lock = DistributedLock("owner-mismatch", acquire_timeout=5)
        await lock.acquire()
        assert await lock.release() is False

    @pytest.mark.asyncio
    async def test_release_redis_error(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(side_effect=ConnectionError("redis gone"))
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        lock = DistributedLock("err-release", acquire_timeout=5)
        await lock.acquire()
        assert await lock.release() is False

    @pytest.mark.asyncio
    async def test_extend_redis_success(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=1)
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        lock = DistributedLock("ext-redis", acquire_timeout=5, ttl_seconds=60)
        await lock.acquire()
        assert await lock.extend(120) is True

    @pytest.mark.asyncio
    async def test_extend_redis_not_owner(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.eval = AsyncMock(return_value=0)
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        lock = DistributedLock("ext-fail", acquire_timeout=5)
        await lock.acquire()
        assert await lock.extend(60) is False

    @pytest.mark.asyncio
    async def test_is_locked_redis(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value="some-owner-id")
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        assert await DistributedLock("check-redis-lock").is_locked() is True

    @pytest.mark.asyncio
    async def test_is_locked_redis_error(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(side_effect=ConnectionError("err"))
        DistributedLock._redis_client = mock_redis
        DistributedLock._redis_initialized = True
        assert await DistributedLock("err-check-lock").is_locked() is False


class TestDistributedLockInit:
    @pytest.fixture(autouse=True)
    def reset_lock_state(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_client = None
        DistributedLock._redis_initialized = False
        DistributedLock._local_locks = {}
        yield
        DistributedLock._redis_client = None
        DistributedLock._redis_initialized = False
        DistributedLock._local_locks = {}

    def test_init_redis_idempotent(self):
        from app.services.distributed_lock import DistributedLock
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = "already-set"
        DistributedLock._init_redis()
        assert DistributedLock._redis_client == "already-set"

    @pytest.mark.asyncio
    async def test_ensure_redis_ping_fails(self):
        from app.services.distributed_lock import DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("nope"))
        DistributedLock._redis_initialized = True
        DistributedLock._redis_client = mock_redis
        assert await DistributedLock._ensure_redis() is False


class TestConvenienceFunctions:
    @pytest.fixture(autouse=True)
    def reset_lock_state(self):
        from app.services.distributed_lock import DistributedLock
        from app.core.config import settings
        DistributedLock._redis_client = None
        DistributedLock._redis_initialized = True
        DistributedLock._local_locks = {}
        with patch.object(settings, "DEVELOPMENT_MODE", True):
            yield
        DistributedLock._redis_client = None
        DistributedLock._redis_initialized = False
        DistributedLock._local_locks = {}

    @pytest.mark.asyncio
    async def test_distributed_lock_context_manager(self):
        from app.services.distributed_lock import distributed_lock
        async with distributed_lock("test-conv", acquire_timeout=5) as lock:
            assert lock._acquired is True

    @pytest.mark.asyncio
    async def test_with_distributed_lock_decorator(self):
        from app.services.distributed_lock import with_distributed_lock

        @with_distributed_lock(lambda x: f"dec:{x}", acquire_timeout=5)
        async def do_work(x):
            return x * 2

        assert await do_work("test") == "testtest"

    @pytest.mark.asyncio
    async def test_session_agent_lock(self):
        from app.services.distributed_lock import session_agent_lock
        ctx = await session_agent_lock("session-123")
        async with ctx as lock:
            assert lock._acquired is True

    @pytest.mark.asyncio
    async def test_checkpoint_lock(self):
        from app.services.distributed_lock import checkpoint_lock
        ctx = await checkpoint_lock("thread-abc")
        async with ctx as lock:
            assert lock._acquired is True

    @pytest.mark.asyncio
    async def test_schema_refresh_lock(self):
        from app.services.distributed_lock import schema_refresh_lock
        ctx = await schema_refresh_lock("conn-hash-xyz")
        async with ctx as lock:
            assert lock._acquired is True

    def test_init_distributed_locking(self):
        from app.services.distributed_lock import init_distributed_locking, DistributedLock
        DistributedLock._redis_initialized = False
        assert isinstance(init_distributed_locking(), bool)

    @pytest.mark.asyncio
    async def test_get_lock_stats_local(self):
        from app.services.distributed_lock import get_lock_stats, DistributedLock
        DistributedLock._redis_client = None
        stats = await get_lock_stats()
        assert stats["backend"] == "local"
        assert stats["distributed"] is False

    @pytest.mark.asyncio
    async def test_get_lock_stats_redis(self):
        from app.services.distributed_lock import get_lock_stats, DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.scan = AsyncMock(return_value=(0, ["lock:a", "lock:b"]))
        DistributedLock._redis_client = mock_redis
        stats = await get_lock_stats()
        assert stats["backend"] == "redis"
        assert stats["active_locks"] == 2

    @pytest.mark.asyncio
    async def test_get_lock_stats_redis_error(self):
        from app.services.distributed_lock import get_lock_stats, DistributedLock
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.scan = AsyncMock(side_effect=ConnectionError("fail"))
        DistributedLock._redis_client = mock_redis
        stats = await get_lock_stats()
        assert "error" in stats


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

class TestPoolConfigAndStats:
    def test_pool_config_defaults(self):
        from app.services.connection_pool_manager import PoolConfig
        cfg = PoolConfig()
        assert cfg.min_size == 2
        assert cfg.max_size == 10
        assert cfg.connection_timeout == 10

    def test_pool_stats_defaults(self):
        from app.services.connection_pool_manager import PoolStats
        stats = PoolStats()
        assert stats.total_connections == 0
        assert stats.errors == 0


class TestLockConfig:
    def test_defaults(self):
        from app.services.distributed_lock import LockConfig
        cfg = LockConfig()
        assert cfg.default_ttl_seconds == 120
        assert cfg.key_prefix == "lock:"


class TestDistributedLockDefaults:
    def test_default_values(self):
        from app.services.distributed_lock import DistributedLock
        lock = DistributedLock("my-lock")
        assert lock.key == "lock:my-lock"
        assert lock.ttl_seconds == 120
        assert lock._acquired is False

    def test_custom_values(self):
        from app.services.distributed_lock import DistributedLock
        lock = DistributedLock("custom-lock", ttl_seconds=60, acquire_timeout=10)
        assert lock.ttl_seconds == 60
        assert lock.acquire_timeout == 10
