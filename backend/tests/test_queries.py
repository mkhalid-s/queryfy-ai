import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from app.main import app
from app.services.sql_generation import SQLGenerationResult

client = TestClient(app)


@pytest.fixture
def mock_validate_request():
    with patch("app.api.queries.validate_request") as mock:
        yield mock


@pytest.fixture
def mock_sql_gen_service():
    with patch("app.api.queries.SQLGenerationService") as mock:
        yield mock


@pytest.fixture
def mock_db_service():
    with patch("app.api.queries.DatabaseService") as mock:
        yield mock


@pytest.fixture
def mock_llm_service():
    with patch("app.api.queries.LLMService") as mock:
        yield mock


@pytest.fixture
def mock_sql_integrity():
    with patch("app.api.queries.sql_integrity") as mock:
        yield mock


@pytest.fixture
def mock_session_store():
    with patch("app.api.queries.session_store") as mock:
        yield mock


@pytest.fixture
def mock_verify_csrf():
    from app.core.csrf_utils import verify_csrf_token
    app.dependency_overrides[verify_csrf_token] = lambda: "valid-token"
    yield
    app.dependency_overrides = {}


def test_generate_sql_success(
    mock_validate_request, mock_sql_gen_service, mock_verify_csrf
):
    # Setup mocks
    mock_validate_request.return_value = {
        "id": "test-session",
        "llm_config": {"provider": "openai"},
        "db_config": {},
    }

    mock_context = MagicMock()
    mock_sql_gen_service.prepare_context = AsyncMock(return_value=(mock_context, None))

    mock_result = SQLGenerationResult(
        success=True,
        sql="SELECT * FROM users",
        query_id="query-123",
        sql_hash="hash-123",
        usage={"tokens": 10},
    )
    mock_sql_gen_service.generate_sql = AsyncMock(return_value=mock_result)

    payload = {"session_id": "test-session", "natural_language": "Show me all users"}

    response = client.post("/api/v1/query/generate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["sql"] == "SELECT * FROM users"
    assert data["query_id"] == "query-123"

    mock_validate_request.assert_called()
    mock_sql_gen_service.prepare_context.assert_called()
    mock_sql_gen_service.generate_sql.assert_called()


def test_generate_sql_error(
    mock_validate_request, mock_sql_gen_service, mock_verify_csrf
):
    mock_validate_request.return_value = {"id": "test-session"}
    mock_sql_gen_service.prepare_context = AsyncMock(return_value=(MagicMock(), None))

    mock_result = SQLGenerationResult(
        success=False, error="Generation failed", message="Could not generate SQL"
    )
    mock_sql_gen_service.generate_sql = AsyncMock(return_value=mock_result)

    payload = {"session_id": "test-session", "natural_language": "Invalid query"}

    response = client.post("/api/v1/query/generate", json=payload)

    assert response.status_code == 200  # Returns 200 with error field
    data = response.json()
    assert data["error"] == "Generation failed"


def test_execute_query_success(
    mock_validate_request, mock_sql_integrity, mock_db_service, mock_verify_csrf
):
    mock_validate_request.return_value = {
        "id": "test-session",
        "db_config": {"db_type": "postgresql", "connection_url": "sqlite:///"},
    }

    mock_sql_integrity.verify_sql.return_value = (True, "Verified")

    mock_db_service.execute_query = AsyncMock(
        return_value={
            "columns": ["id", "name"],
            "rows": [{"id": 1, "name": "Test"}],
            "row_count": 1,
        }
    )

    payload = {
        "session_id": "test-session",
        "sql_query": "SELECT * FROM users",
        "query_id": "query-123",
        "sql_hash": "hash-123",
    }

    response = client.post("/api/v1/query/execute", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["row_count"] == 1
    assert len(data["rows"]) == 1

    mock_sql_integrity.verify_sql.assert_called()
    mock_db_service.execute_query.assert_called()


def test_execute_query_verification_failed(
    mock_validate_request, mock_sql_integrity, mock_verify_csrf
):
    mock_validate_request.return_value = {"id": "test-session"}
    mock_sql_integrity.verify_sql.return_value = (False, "Tampered SQL")

    payload = {
        "session_id": "test-session",
        "sql_query": "DROP TABLE users",
        "query_id": "query-123",
        "sql_hash": "hash-123",
    }

    response = client.post("/api/v1/query/execute", json=payload)

    assert response.status_code == 403
    assert "Security check failed" in response.json()["detail"]


def test_explain_sql_success(mock_validate_request, mock_llm_service, mock_verify_csrf):
    mock_validate_request.return_value = {
        "id": "test-session",
        "llm_config": {"provider": "openai"},
        "db_config": {"db_type": "postgresql", "connection_url": "sqlite:///"},
    }

    # Mock vector_db.get_full_schema_text via patch in the test function or fixture
    with patch("app.api.queries.vector_db.get_full_schema_text", return_value="schema"):
        mock_llm_service.explain_sql = AsyncMock(
            return_value=(
                "This query selects users",
                {"tokens": 10},
            )
        )

        payload = {"session_id": "test-session", "sql_query": "SELECT * FROM users"}

        response = client.post("/api/v1/query/explain", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["explanation"] == "This query selects users"


def test_get_history(mock_session_store):
    # Need to patch get_session dependency which is used in get_history
    with patch("app.api.queries.get_session") as mock_get_session:
        mock_get_session.return_value = {
            "history": [
                {
                    "id": "hist-1",
                    "query": "test",
                    "sql": "SELECT 1",
                    "timestamp": "2023-01-01T00:00:00Z",
                }
            ]
        }

        response = client.get("/api/v1/history/test-session")

        assert response.status_code == 200
        data = response.json()
        assert len(data["history"]) == 1
        assert data["history"][0]["query"] == "test"
