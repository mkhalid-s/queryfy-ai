"""
QueryfyAI - Health Endpoint Tests
"""

from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Test health check endpoints"""

    def test_health_endpoint(self, client: TestClient):
        """Test main health check endpoint returns success"""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "app" in data
        assert "version" in data

    def test_liveness_endpoint(self, client: TestClient):
        """Test liveness probe returns alive status"""
        response = client.get("/health/live")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "alive"
        assert "timestamp" in data

    def test_readiness_endpoint(self, client: TestClient):
        """Test readiness probe returns ready status"""
        response = client.get("/health/ready")
        assert response.status_code == 200

        data = response.json()
        assert "ready" in data
        assert "checks" in data
        assert "timestamp" in data


class TestAPIEndpoints:
    """Test API endpoints"""

    def test_root_endpoint(self, client: TestClient):
        """Test root endpoint returns app info"""
        response = client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert "app" in data
        assert data["status"] == "running"

    def test_db_types_endpoint(self, client: TestClient):
        """Test database types endpoint returns supported databases"""
        response = client.get("/api/v1/db-types")
        assert response.status_code == 200

        data = response.json()
        assert "db_types" in data
        assert len(data["db_types"]) > 0

        # Verify PostgreSQL is in the list
        db_ids = [db["id"] for db in data["db_types"]]
        assert "postgresql" in db_ids
        assert "mysql" in db_ids

    def test_default_config_endpoint(self, client: TestClient):
        """Test default config endpoint"""
        response = client.get("/api/v1/config/defaults")
        assert response.status_code == 200

        data = response.json()
        assert "has_defaults" in data
        assert "llm_config" in data
        assert "db_config" in data
