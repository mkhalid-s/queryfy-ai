"""
Unit tests for Query Tools.

Tests individual tool functions including:
- execute_sql: Basic SQL execution
- execute_and_analyze: Execution with analysis and sampling
- find_similar_queries: Vector DB similarity search
- detect_data_characteristics: Sampling bias detection

Focus on memory guards, row limits, and error handling.
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch


pytestmark = pytest.mark.unit


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def mock_tool_context():
    """Mock ToolContext for tests"""
    from app.services.tools.registry import ToolContext

    context = MagicMock(spec=ToolContext)
    context.connection_url = "postgresql://test:test@localhost/testdb"
    context.db_config = MagicMock()
    context.db_config.database_type = "postgresql"
    context.session_id = "test-session"
    context.vector_db = MagicMock()

    return context


@pytest.fixture
def sample_small_result():
    """Small result set (<1000 rows)"""
    return {
        "columns": ["id", "name", "revenue"],
        "rows": [
            {"id": 1, "name": "Customer A", "revenue": 50000},
            {"id": 2, "name": "Customer B", "revenue": 45000},
            {"id": 3, "name": "Customer C", "revenue": 40000}
        ],
        "row_count": 3,
        "execution_time_ms": 10
    }


@pytest.fixture
def sample_large_result():
    """Large result set (>1000 rows for sampling)"""
    rows = [{"id": i, "name": f"Customer {i}", "revenue": i * 1000} for i in range(1, 1501)]
    return {
        "columns": ["id", "name", "revenue"],
        "rows": rows,
        "row_count": 1500,
        "execution_time_ms": 100
    }


# ============================================
# Test: execute_sql
# ============================================

@pytest.mark.asyncio
async def test_execute_sql_success(mock_tool_context, sample_small_result):
    """Test execute_sql returns results for valid query"""
    from app.services.tools.query_tools import execute_sql

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = sample_small_result

        result_str = await execute_sql(
            context=mock_tool_context,
            sql="SELECT * FROM customers LIMIT 10"
        )

        result = json.loads(result_str)

        assert result["success"] is True
        assert "columns" in result
        assert result["row_count"] == 3
        assert len(result["rows"]) == 3


@pytest.mark.asyncio
async def test_execute_sql_syntax_error(mock_tool_context):
    """Test execute_sql handles SQL syntax errors"""
    from app.services.tools.query_tools import execute_sql

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        # Simulate error
        mock_execute.side_effect = Exception("syntax error at or near 'SELCT'")

        result_str = await execute_sql(
            context=mock_tool_context,
            sql="SELCT * FROM customers"  # typo
        )

        result = json.loads(result_str)

        assert result["success"] is False
        assert "error" in result
        assert "syntax" in result["error"].lower() or "SELCT" in result["error"]


@pytest.mark.asyncio
async def test_execute_sql_column_not_found(mock_tool_context):
    """Test execute_sql handles column not found errors"""
    from app.services.tools.query_tools import execute_sql

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.side_effect = Exception("column 'invalid_column' does not exist")

        result_str = await execute_sql(
            context=mock_tool_context,
            sql="SELECT invalid_column FROM customers"
        )

        result = json.loads(result_str)

        assert result["success"] is False
        assert "error" in result
        assert "column" in result["error"].lower() or "invalid_column" in result["error"]


# ============================================
# Test: execute_and_analyze - Small Datasets
# ============================================

@pytest.mark.asyncio
async def test_execute_and_analyze_small_dataset(mock_tool_context, sample_small_result):
    """Test execute_and_analyze returns full analysis for <1000 rows"""
    from app.services.tools.query_tools import execute_and_analyze

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = sample_small_result

        # Mock LLM service for insights
        with patch('app.services.llm_service.LLMService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools.return_value = {
                "content": json.dumps([
                    {"type": "trend", "message": "Revenue is stable across customers"}
                ])
            }
            mock_llm_class.return_value = mock_llm

            result_str = await execute_and_analyze(
                context=mock_tool_context,
                sql="SELECT * FROM customers LIMIT 10"
            )

            result = json.loads(result_str)

            assert result["success"] is True
            assert result["row_count"] == 3
            # Should include full dataset (no sampling)
            assert len(result["rows"]) == 3
            assert "insights" in result
            # Should NOT have sampling warnings
            assert "sampling_applied" not in result or result.get("sampling_applied") is False


# ============================================
# Test: execute_and_analyze - Sampling
# ============================================

@pytest.mark.asyncio
async def test_execute_and_analyze_sampling_large_dataset(mock_tool_context, sample_large_result):
    """Test execute_and_analyze applies sampling for >1000 rows"""
    from app.services.tools.query_tools import execute_and_analyze

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = sample_large_result

        with patch('app.services.llm_service.LLMService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools.return_value = {"content": "[]"}
            mock_llm_class.return_value = mock_llm

            result_str = await execute_and_analyze(
                context=mock_tool_context,
                sql="SELECT * FROM customers"
            )

            result = json.loads(result_str)

            assert result["success"] is True
            assert result["row_count"] == 1500  # Full count reported
            # Phase 4.1: full rows live in the ResultCache; the tool
            # response carries only a preview (<=20) and the rows_ref
            # handle. This is what keeps the tool payload <50KB.
            assert len(result["rows"]) <= 20, (
                f"expected preview of <=20 rows in tool payload, "
                f"got {len(result['rows'])}"
            )
            assert result.get("rows_cached") is True
            assert result.get("rows_ref", "").startswith("result:")
            # Should have insights
            assert "insights" in result


@pytest.mark.asyncio
async def test_execute_and_analyze_respects_row_limit(mock_tool_context):
    """Test execute_and_analyze enforces default row limit (1000)"""
    from app.services.tools.query_tools import execute_and_analyze

    # Mock result that respects default limit (1000)
    limited_result = {
        "columns": ["id"],
        "rows": [{"id": i} for i in range(1000)],
        "row_count": 1000,
        "execution_time_ms": 50
    }

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = limited_result

        with patch('app.services.llm_service.LLMService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools.return_value = {"content": "[]"}
            mock_llm_class.return_value = mock_llm

            # No explicit limit provided - should use default (1000)
            result_str = await execute_and_analyze(
                context=mock_tool_context,
                sql="SELECT * FROM huge_table"
            )

            json.loads(result_str)

            # Verify limit was passed to execute_query
            mock_execute.assert_called_once()
            call_kwargs = mock_execute.call_args.kwargs
            assert call_kwargs["limit"] == 1000  # Default limit


@pytest.mark.asyncio
async def test_execute_and_analyze_custom_limit(mock_tool_context):
    """Test execute_and_analyze respects custom limit parameter"""
    from app.services.tools.query_tools import execute_and_analyze

    result_500 = {
        "columns": ["id"],
        "rows": [{"id": i} for i in range(500)],
        "row_count": 500,
        "execution_time_ms": 25
    }

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = result_500

        with patch('app.services.llm_service.LLMService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools.return_value = {"content": "[]"}
            mock_llm_class.return_value = mock_llm

            result_str = await execute_and_analyze(
                context=mock_tool_context,
                sql="SELECT * FROM customers",
                limit=500  # Custom limit
            )

            result = json.loads(result_str)

            assert result["success"] is True
            assert result["row_count"] == 500


# ============================================
# Test: execute_and_analyze - Memory Guard
# ============================================

@pytest.mark.asyncio
async def test_execute_and_analyze_memory_guard(mock_tool_context):
    """Test execute_and_analyze rejects datasets >50MB"""
    from app.services.tools.query_tools import execute_and_analyze

    # Create result just over 50MB threshold
    # 100 rows × 520KB per row ≈ 52MB (optimized from 600 rows × 100KB = 60MB)
    large_strings = [["x" * 520000] for _ in range(100)]  # ~52MB
    large_result = {
        "columns": ["data"],
        "rows": large_strings,
        "row_count": 100
    }

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = large_result

        result_str = await execute_and_analyze(
            context=mock_tool_context,
            sql="SELECT massive_column FROM big_table"
        )

        result = json.loads(result_str)

        # Should be rejected or heavily sampled
        if result["success"] is False:
            assert "too large" in result.get("error", "").lower() or "memory" in result.get("error", "").lower()
        else:
            # If accepted, must be sampled down significantly
            assert len(result["rows"]) < 100


@pytest.mark.asyncio
async def test_execute_and_analyze_string_truncation(mock_tool_context):
    """Test execute_and_analyze truncates long strings for analysis"""
    from app.services.tools.query_tools import execute_and_analyze

    # Result with very long string values
    long_string_result = {
        "columns": ["id", "description"],
        "rows": [
            {"id": 1, "description": "A" * 500},  # 500 char string
            {"id": 2, "description": "B" * 500},
            {"id": 3, "description": "C" * 500}
        ],
        "row_count": 3,
        "execution_time_ms": 10
    }

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = long_string_result

        with patch('app.services.llm_service.LLMService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools.return_value = {"content": "[]"}
            mock_llm_class.return_value = mock_llm

            result_str = await execute_and_analyze(
                context=mock_tool_context,
                sql="SELECT * FROM descriptions"
            )

            result = json.loads(result_str)

            assert result["success"] is True
            # Long strings should be truncated (sanitize_value truncates at 100 chars)
            for row in result["rows"]:
                desc = row.get("description", "")
                if isinstance(desc, str):
                    assert len(desc) <= 103  # 100 chars + "..."


# ============================================
# Test: detect_data_characteristics
# ============================================

def test_detect_time_series_data():
    """Test detection of time-series columns"""
    from app.services.tools.query_tools import detect_data_characteristics

    columns = ["order_id", "order_date", "total_amount"]
    rows = [
        {"order_id": 1, "order_date": "2025-01-01", "total_amount": 100},
        {"order_id": 2, "order_date": "2025-01-02", "total_amount": 150}
    ]

    result = detect_data_characteristics(columns, rows)

    assert result["has_time_series"] is True
    assert result["sampling_appropriate"] is False
    assert any("time-series" in w.lower() for w in result["warnings"])


def test_detect_sequential_id():
    """Test detection of sequential ID columns"""
    from app.services.tools.query_tools import detect_data_characteristics

    columns = ["id", "name"]
    # Sequential IDs: 1, 2, 3, 4, ...
    rows = [{"id": i, "name": f"Item {i}"} for i in range(1, 101)]

    result = detect_data_characteristics(columns, rows)

    assert result["has_id_sequence"] is True
    assert result["sampling_appropriate"] is False
    assert any("sequential" in w.lower() for w in result["warnings"])


def test_detect_high_variance():
    """Test detection of outliers/high variance in numeric data"""
    from app.services.tools.query_tools import detect_data_characteristics

    columns = ["id", "revenue"]
    # High variance: mostly small values, one huge outlier
    rows = [{"id": i, "revenue": 100 if i < 99 else 100000} for i in range(1, 101)]

    result = detect_data_characteristics(columns, rows)

    assert result["has_outliers_risk"] is True
    assert any("variance" in w.lower() or "outlier" in w.lower() for w in result["warnings"])


def test_detect_no_issues():
    """Test normal data with no sampling issues"""
    from app.services.tools.query_tools import detect_data_characteristics

    columns = ["customer_id", "region", "revenue"]
    rows = [
        {"customer_id": 101, "region": "North", "revenue": 5000},
        {"customer_id": 205, "region": "South", "revenue": 4800},
        {"customer_id": 310, "region": "East", "revenue": 5200}
    ]

    result = detect_data_characteristics(columns, rows)

    # Non-sequential IDs, no time series, normal variance
    assert result["sampling_appropriate"] is True
    assert len(result["warnings"]) == 0


# ============================================
# Test: find_similar_queries
# ============================================

@pytest.mark.asyncio
async def test_find_similar_queries_success(mock_tool_context):
    """Test find_similar_queries returns formatted similar queries"""
    from app.services.tools.query_tools import find_similar_queries

    with patch('app.services.vector_db.vector_db') as mock_vector_db:
        mock_vector_db.find_similar_queries.return_value = [
            {
                "query": "Show top customers",
                "sql": "SELECT customer_name, revenue FROM customers ORDER BY revenue DESC LIMIT 10",
                "rating": 5
            },
            {
                "query": "List best customers by sales",
                "sql": "SELECT * FROM customers ORDER BY total_sales DESC LIMIT 10",
                "rating": 4
            }
        ]

        result = await find_similar_queries(
            context=mock_tool_context,
            query="Who are my best customers?",
            limit=3
        )

        assert "Similar queries found" in result
        assert "Show top customers" in result
        assert "SELECT customer_name" in result
        assert "****" in result  # 5-star rating


@pytest.mark.asyncio
async def test_find_similar_queries_no_results(mock_tool_context):
    """Test find_similar_queries handles no matches"""
    from app.services.tools.query_tools import find_similar_queries

    with patch('app.services.vector_db.vector_db') as mock_vector_db:
        mock_vector_db.find_similar_queries.return_value = []

        result = await find_similar_queries(
            context=mock_tool_context,
            query="Unique question never asked before",
            limit=3
        )

        assert "No similar queries found" in result
        assert "new type of question" in result.lower()


@pytest.mark.asyncio
async def test_find_similar_queries_no_connection(mock_tool_context):
    """Test find_similar_queries requires database connection"""
    from app.services.tools.query_tools import find_similar_queries

    # Remove connection URL
    mock_tool_context.connection_url = None

    result = await find_similar_queries(
        context=mock_tool_context,
        query="Test query"
    )

    assert "Error" in result
    assert "database connection" in result.lower()


# ============================================
# Test: sanitize_value
# ============================================

def test_sanitize_value_preserves_primitives():
    """Test sanitize_value preserves None, int, float, bool"""
    from app.services.tools.query_tools import sanitize_value

    assert sanitize_value(None) is None
    assert sanitize_value(42) == 42
    assert sanitize_value(3.14) == 3.14
    assert sanitize_value(True) is True
    assert sanitize_value(False) is False


def test_sanitize_value_converts_to_string():
    """Test sanitize_value converts objects to string"""
    from app.services.tools.query_tools import sanitize_value

    from datetime import date
    result = sanitize_value(date(2025, 1, 1))
    assert isinstance(result, str)
    assert "2025" in result


def test_sanitize_value_removes_control_chars():
    """Test sanitize_value removes control characters"""
    from app.services.tools.query_tools import sanitize_value

    # String with control character (null byte)
    dirty = "Hello\x00World\x1fTest"
    clean = sanitize_value(dirty)

    assert "\x00" not in clean
    assert "\x1f" not in clean
    assert "Hello" in clean
    assert "World" in clean


def test_sanitize_value_truncates_long_strings():
    """Test sanitize_value truncates strings >100 chars"""
    from app.services.tools.query_tools import sanitize_value

    long_string = "A" * 150
    result = sanitize_value(long_string)

    assert len(result) <= 103  # 100 + "..."
    assert result.endswith("...")


# ============================================
# Test: Error Classification
# ============================================

@pytest.mark.asyncio
async def test_execute_sql_classifies_timeout_error(mock_tool_context):
    """Test execute_sql classifies timeout errors as transient"""
    from app.services.tools.query_tools import execute_sql

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.side_effect = Exception("query timeout exceeded")

        result_str = await execute_sql(
            context=mock_tool_context,
            sql="SELECT * FROM slow_query"
        )

        result = json.loads(result_str)

        assert result["success"] is False
        assert "timeout" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_sql_classifies_connection_error(mock_tool_context):
    """Test execute_sql handles connection errors"""
    from app.services.tools.query_tools import execute_sql

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.side_effect = Exception("connection refused")

        result_str = await execute_sql(
            context=mock_tool_context,
            sql="SELECT * FROM customers"
        )

        result = json.loads(result_str)

        assert result["success"] is False
        assert "connection" in result.get("error", "").lower() or "refused" in result.get("error", "").lower()


# ============================================
# Test: Edge Cases
# ============================================

@pytest.mark.asyncio
async def test_execute_and_analyze_empty_result(mock_tool_context):
    """Test execute_and_analyze handles empty result sets"""
    from app.services.tools.query_tools import execute_and_analyze

    empty_result = {
        "columns": [],
        "rows": [],
        "row_count": 0,
        "execution_time_ms": 0
    }

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = empty_result

        with patch('app.services.llm_service.LLMService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools.return_value = {"content": "[]"}
            mock_llm_class.return_value = mock_llm

            result_str = await execute_and_analyze(
                context=mock_tool_context,
                sql="SELECT * FROM customers WHERE 1=0"  # Always empty
            )

            result = json.loads(result_str)

            assert result["success"] is True
            assert result["analyzed_rows"] == 0
            assert len(result.get("insights", [])) >= 0


@pytest.mark.asyncio
async def test_execute_and_analyze_null_values(mock_tool_context):
    """Test execute_and_analyze handles NULL values correctly"""
    from app.services.tools.query_tools import execute_and_analyze

    null_result = {
        "columns": ["id", "name", "email"],
        "rows": [
            {"id": 1, "name": "Customer A", "email": None},
            {"id": 2, "name": None, "email": "customer@example.com"},
            {"id": 3, "name": "Customer C", "email": "c@example.com"}
        ],
        "row_count": 3,
        "execution_time_ms": 10
    }

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = null_result

        with patch('app.services.llm_service.LLMService') as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.call_with_tools.return_value = {"content": "[]"}
            mock_llm_class.return_value = mock_llm

            result_str = await execute_and_analyze(
                context=mock_tool_context,
                sql="SELECT * FROM customers"
            )

            result = json.loads(result_str)

            assert result["success"] is True
            # NULLs should be preserved
            assert result["rows"][0]["email"] is None
            assert result["rows"][1]["name"] is None


@pytest.mark.asyncio
async def test_execute_sql_permission_denied(mock_tool_context):
    """Test execute_sql handles permission denied errors"""
    from app.services.tools.query_tools import execute_sql

    with patch('app.services.database_service.DatabaseService.execute_query', new_callable=AsyncMock) as mock_execute:
        mock_execute.side_effect = Exception("permission denied for table customers")

        result_str = await execute_sql(
            context=mock_tool_context,
            sql="SELECT * FROM customers"
        )

        result = json.loads(result_str)

        assert result["success"] is False
        assert "permission" in result.get("error", "").lower()


# =============================================================================
# PII column detection (_pii_columns_for_table)
# =============================================================================


class TestPiiColumnDetection:
    """
    Dictionary-driven masking with a conservative name-heuristic
    fallback. The detector NEVER raises; an empty result just means
    no masking will happen at the call site.
    """

    def test_explicit_is_pii_true_masks_column(self):
        from app.services.tools.query_tools import _pii_columns_for_table

        result = _pii_columns_for_table(
            columns=["id", "email", "created_at"],
            table_descriptions={
                "email": {"is_pii": True, "description": "user email"},
            },
        )
        assert result == {"email"}

    def test_explicit_is_pii_false_overrides_heuristic(self):
        """An explicit dictionary entry wins over the name heuristic."""
        from app.services.tools.query_tools import _pii_columns_for_table

        # ``email_template`` contains "email" which would hit the heuristic,
        # but the dictionary says it's not PII — respect that.
        result = _pii_columns_for_table(
            columns=["id", "email_template"],
            table_descriptions={
                "email_template": {"is_pii": False, "description": "template body"},
            },
        )
        assert result == set()

    def test_heuristic_fires_when_no_description_exists(self):
        """Columns with no dictionary entry match the substring heuristic."""
        from app.services.tools.query_tools import _pii_columns_for_table

        result = _pii_columns_for_table(
            columns=["id", "customer_email", "phone_number", "ssn", "address_line_1"],
            table_descriptions=None,
        )
        # All 4 non-id columns match the heuristic.
        assert result == {"customer_email", "phone_number", "ssn", "address_line_1"}

    def test_heuristic_is_case_insensitive(self):
        from app.services.tools.query_tools import _pii_columns_for_table

        result = _pii_columns_for_table(
            columns=["CustomerEmail", "API_KEY", "PhoneNumber"],
            table_descriptions=None,
        )
        assert result == {"CustomerEmail", "API_KEY", "PhoneNumber"}

    def test_non_pii_columns_pass_through(self):
        from app.services.tools.query_tools import _pii_columns_for_table

        result = _pii_columns_for_table(
            columns=["id", "created_at", "status", "amount", "region"],
            table_descriptions={"status": {"is_pii": False}},
        )
        assert result == set()

    def test_empty_columns_returns_empty_set(self):
        from app.services.tools.query_tools import _pii_columns_for_table

        assert _pii_columns_for_table(columns=[], table_descriptions=None) == set()
        assert _pii_columns_for_table(columns=[], table_descriptions={}) == set()

    def test_missing_is_pii_key_treated_as_false(self):
        """Partial dictionary entries (no is_pii field) should not mask."""
        from app.services.tools.query_tools import _pii_columns_for_table

        # ``user_notes`` has a description but no is_pii → not masked.
        # ``email`` has no entry → heuristic fires.
        result = _pii_columns_for_table(
            columns=["user_notes", "email"],
            table_descriptions={"user_notes": {"description": "notes field"}},
        )
        assert result == {"email"}


class TestRedactPiiInRows:
    """
    _redact_pii_in_rows mutates rows in place — the mutation must
    cascade to any shallow-copied downstream list (sampling,
    preview, cache write all share dict references).
    """

    def test_mutation_cascades_to_shallow_copied_slice(self):
        """Slices point at the same dict objects; mutating rows mutates slices."""
        from app.services.tools.query_tools import _redact_pii_in_rows

        rows = [
            {"id": 1, "email": "alice@example.com", "amount": 100},
            {"id": 2, "email": "bob@example.com", "amount": 200},
        ]
        preview = rows[:1]  # Shallow slice — points at row[0]
        _redact_pii_in_rows(rows, {"email"})
        assert rows[0]["email"] == "[REDACTED]"
        assert preview[0]["email"] == "[REDACTED]"
        # Non-PII columns untouched
        assert rows[0]["id"] == 1
        assert rows[0]["amount"] == 100

    def test_noop_on_empty_pii_set(self):
        from app.services.tools.query_tools import _redact_pii_in_rows

        rows = [{"id": 1, "email": "alice@example.com"}]
        _redact_pii_in_rows(rows, set())
        assert rows[0]["email"] == "alice@example.com"

    def test_noop_on_empty_rows(self):
        from app.services.tools.query_tools import _redact_pii_in_rows

        rows = []
        _redact_pii_in_rows(rows, {"email"})
        assert rows == []

    def test_none_values_preserved(self):
        """Redaction should not overwrite None (distinguishes null from PII)."""
        from app.services.tools.query_tools import _redact_pii_in_rows

        rows = [{"id": 1, "email": None}]
        _redact_pii_in_rows(rows, {"email"})
        assert rows[0]["email"] is None


class TestRedactInsightCellValues:
    """
    _redact_insight_cell_values scrubs cell values that leak through
    the detect_insights output shape: outlier.value / .identifier
    and significant_diffs[].group.
    """

    def test_redacts_outlier_value_when_column_is_pii(self):
        from app.services.tools.query_tools import _redact_insight_cell_values

        insights = [{
            "type": "anomaly",
            "column_name": "email",
            "metrics": {
                "outliers": [
                    {"value": "alice@example.com", "z_score": 3.2, "row_index": 42},
                    {"value": "bob@example.com", "z_score": 3.5, "row_index": 99},
                ]
            },
        }]
        result = _redact_insight_cell_values(insights, {"email"})
        assert result[0]["metrics"]["outliers"][0]["value"] == "[REDACTED]"
        assert result[0]["metrics"]["outliers"][1]["value"] == "[REDACTED]"
        # z_score and row_index preserved
        assert result[0]["metrics"]["outliers"][0]["z_score"] == 3.2

    def test_redacts_identifier_partial_when_pii_column_present(self):
        """identifier strings like 'col=value' — redact only PII parts."""
        from app.services.tools.query_tools import _redact_insight_cell_values

        insights = [{
            "type": "anomaly",
            "metrics": {
                "outliers": [
                    {"value": 999.5, "identifier": "email=alice@example.com, region=east"},
                ]
            },
        }]
        result = _redact_insight_cell_values(insights, {"email"})
        ident = result[0]["metrics"]["outliers"][0]["identifier"]
        assert "alice@example.com" not in ident
        assert "[REDACTED]" in ident
        # Non-PII part preserved
        assert "region=east" in ident

    def test_redacts_comparison_group_when_group_column_is_pii(self):
        from app.services.tools.query_tools import _redact_insight_cell_values

        insights = [{
            "type": "comparison",
            "metrics": {
                "significant_diffs": [
                    {"group_column": "email", "group": "alice@example.com", "diff_pct": 45.0},
                    {"group_column": "region", "group": "east", "diff_pct": 30.0},
                ]
            },
        }]
        result = _redact_insight_cell_values(insights, {"email"})
        diffs = result[0]["metrics"]["significant_diffs"]
        assert diffs[0]["group"] == "[REDACTED]"
        assert diffs[1]["group"] == "east"  # region is not PII

    def test_noop_on_empty_pii_set(self):
        from app.services.tools.query_tools import _redact_insight_cell_values

        insights = [{"type": "anomaly", "metrics": {"outliers": [{"value": "x"}]}}]
        result = _redact_insight_cell_values(insights, set())
        assert result[0]["metrics"]["outliers"][0]["value"] == "x"

    def test_pass_through_non_list_input(self):
        from app.services.tools.query_tools import _redact_insight_cell_values

        # Defensive — must not raise on None or dict inputs.
        assert _redact_insight_cell_values(None, {"email"}) is None
        assert _redact_insight_cell_values({"not_a_list": True}, {"email"}) == {"not_a_list": True}

    def test_missing_metrics_dict_handled_gracefully(self):
        from app.services.tools.query_tools import _redact_insight_cell_values

        # Insight without metrics at all — must not raise.
        insights = [{"type": "info", "description": "flat data"}]
        result = _redact_insight_cell_values(insights, {"email"})
        assert result == [{"type": "info", "description": "flat data"}]
