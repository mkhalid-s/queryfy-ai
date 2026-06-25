import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_validate_request():
    with patch("app.api.schema.validate_request") as mock:
        yield mock


@pytest.fixture
def mock_db_service():
    with patch("app.api.schema.DatabaseService") as mock:
        yield mock


@pytest.fixture
def mock_vector_db():
    with patch("app.api.schema.vector_db") as mock:
        yield mock


@pytest.fixture
def mock_session_store():
    with patch("app.api.schema.session_store") as mock:
        yield mock


@pytest.fixture
def mock_verify_csrf():
    from app.core.csrf_utils import verify_csrf_token
    app.dependency_overrides[verify_csrf_token] = lambda: "valid-token"
    yield
    app.dependency_overrides = {}


@pytest.fixture
def mock_get_session():
    with patch("app.api.schema.get_session") as mock:
        yield mock


def test_refresh_schema_success(mock_validate_request, mock_verify_csrf):
    mock_validate_request.return_value = {
        "id": "test-session",
        "db_config": {"db_type": "postgresql", "connection_url": "sqlite:///"},
    }

    response = client.post("/api/v1/schema/refresh?session_id=test-session")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert "started" in data["message"]

    mock_validate_request.assert_called()


def test_get_schema_success(mock_get_session, mock_vector_db):
    mock_get_session.return_value = {
        "id": "test-session",
        "db_config": {"db_type": "postgresql", "connection_url": "sqlite:///"},
    }

    mock_vector_db.get_full_schema_text.return_value = "CREATE TABLE users..."

    response = client.get("/api/v1/schema/test-session")

    assert response.status_code == 200
    data = response.json()
    assert data["schema_text"] == "CREATE TABLE users..."


def test_get_schema_not_found(mock_get_session, mock_vector_db, mock_db_service):
    mock_get_session.return_value = {
        "id": "test-session",
        "db_config": {"db_type": "postgresql", "connection_url": "sqlite:///"},
    }

    mock_vector_db.get_full_schema_text.return_value = "No schema available"
    mock_db_service.extract_schema = AsyncMock(
        return_value={
            "db_type": "postgresql",
            "tables": [{"name": "users"}],
        }
    )

    response = client.get("/api/v1/schema/test-session")

    assert response.status_code == 200
    data = response.json()
    assert data["db_type"] == "postgresql"
    assert len(data["tables"]) == 1


def test_vector_db_stats(mock_vector_db):
    mock_vector_db.db_type = "chromadb"
    mock_vector_db.schema_collection.count.return_value = 10
    mock_vector_db.query_collection.count.return_value = 5
    mock_vector_db.schema_collection.get.return_value = {"metadatas": []}

    response = client.get("/api/v1/schema/vector-db/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["db_type"] == "chromadb"
    assert data["collections"]["schema_embeddings"] == 10
    assert data["collections"]["query_history"] == 5


def test_test_embedding(mock_vector_db):
    mock_vector_db.embedding_fn = True
    mock_vector_db._generate_embeddings.return_value = [[0.1, 0.2, 0.3]]

    response = client.get("/api/v1/schema/test-embedding")

    assert response.status_code == 200
    data = response.json()
    assert data["embedding_generated"] is True
    assert data["embedding_dimension"] == 3
