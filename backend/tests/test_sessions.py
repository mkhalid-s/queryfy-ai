import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.session_store import SessionStore
from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_session_store():
    with patch.object(SessionStore, "create_session") as mock_create, patch.object(
        SessionStore, "get"
    ) as mock_get, patch.object(SessionStore, "delete") as mock_delete:

        mock = MagicMock()
        mock.create_session = mock_create
        mock.get = mock_get
        mock.delete = mock_delete
        yield mock


@pytest.fixture
def mock_db_service():
    with patch("app.api.sessions.DatabaseService") as mock:
        yield mock


@pytest.fixture
def mock_llm_service():
    with patch("app.api.sessions.LLMService") as mock:
        yield mock


@pytest.fixture
def mock_token_manager():
    with patch("app.api.sessions.token_manager") as mock:
        yield mock


@pytest.fixture
def mock_background_tasks():
    with patch("fastapi.BackgroundTasks.add_task") as mock:
        yield mock


def test_get_default_config():
    response = client.get("/api/v1/config/defaults")
    assert response.status_code == 200
    data = response.json()
    assert "llm_config" in data
    assert "db_config" in data
    assert "has_defaults" in data


def test_create_session_success(
    mock_session_store, mock_db_service, mock_llm_service, mock_token_manager
):
    # Setup mocks
    mock_db_service.validate_connection_url.return_value = (True, "")
    mock_db_service.test_connection = AsyncMock(
        return_value={
            "success": True,
            "message": "Connected",
        }
    )
    mock_llm_service.generate_sql = AsyncMock(
        return_value=("OK", {})
    )  # For connection test
    mock_session_store.create_session.return_value = "test-session-id"

    payload = {
        "llm_config": {"provider": "openai", "api_key": "sk-test", "model": "gpt-4"},
        "db_config": {
            "db_type": "postgresql",
            "connection_url": "postgresql://user:pass@localhost:5432/db",
        },
    }

    # Mock validate_llm_connection internal call
    with patch(
        "app.api.sessions.validate_llm_connection",
        new_callable=AsyncMock,
        return_value={"success": True, "message": "Connected"},
    ):
        response = client.post("/api/v1/sessions", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session-id"
    assert "csrf_token" in data

    # Verify mocks called
    mock_db_service.validate_connection_url.assert_called()
    mock_db_service.test_connection.assert_called()
    mock_session_store.create_session.assert_called()


def test_create_session_invalid_db_url(mock_db_service):
    mock_db_service.validate_connection_url.return_value = (False, "Invalid URL format")

    payload = {
        "llm_config": {"provider": "openai", "api_key": "sk-test"},
        "db_config": {"db_type": "postgresql", "connection_url": "invalid-url"},
    }

    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 400
    assert "Invalid connection URL" in response.json()["detail"]


def test_get_session_success(mock_session_store):
    mock_session_store.get.return_value = {
        "id": "test-session-id",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "locked": False,
        "history": [],
        "db_config": {"db_type": "postgresql"},
        "llm_config": {"provider": "openai"},
        "schema_ready": True,
        "schema_table_count": 10,
    }

    response = client.get("/api/v1/sessions/test-session-id")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-session-id"
    assert data["db_type"] == "postgresql"
    assert data["schema_ready"] is True


def test_get_session_not_found(mock_session_store):
    mock_session_store.get.return_value = None

    response = client.get("/api/v1/sessions/non-existent")
    assert response.status_code == 404


def test_delete_session(mock_session_store):
    mock_session_store.get.return_value = {
        "id": "test-session-id"
    }  # For cleanup checks if any

    response = client.delete("/api/v1/sessions/test-session-id")
    assert response.status_code == 200
    assert response.json()["message"] == "Session deleted"
    mock_session_store.delete.assert_called_with("test-session-id")


def test_schema_status(mock_session_store):
    mock_session_store.get.return_value = {
        "id": "test-session-id",
        "schema_ready": False,
        "schema_error": None,
        "schema_table_count": 0,
    }

    response = client.get("/api/v1/sessions/test-session-id/schema-status")
    assert response.status_code == 200
    data = response.json()
    assert data["schema_ready"] is False
    assert "extraction in progress" in data["message"]
