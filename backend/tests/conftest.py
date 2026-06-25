"""
QueryfyAI - Pytest Fixtures
"""

import pytest
from fastapi.testclient import TestClient
import asyncio
from contextlib import asynccontextmanager


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@asynccontextmanager
async def test_lifespan(app):
    """Lightweight lifespan for tests - no database, no migrations, no heavy initialization"""
    # Startup: minimal initialization
    yield
    # Shutdown: nothing to clean up


@pytest.fixture
def test_app():
    """Lightweight FastAPI app for testing without migrations or heavy initialization"""
    from fastapi import FastAPI
    from app.api import (
        chat,
        consolidated,
        data_dictionary,
        dml,
        health,
        metrics,
        queries,
        schema,
        sessions,
    )
    from fastapi.middleware.cors import CORSMiddleware
    from app.core.csrf_utils import verify_csrf_token

    # Create a minimal app with test lifespan
    app = FastAPI(lifespan=test_lifespan)

    # Override CSRF dependency to always return test token
    def override_csrf_token():
        return "test-csrf-token"

    app.dependency_overrides[verify_csrf_token] = override_csrf_token

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Root endpoint (defined on app in main.py, not via router)
    @app.get("/")
    async def root():
        return {
            "app": "QueryfyAI-Test",
            "version": "test",
            "status": "running",
        }

    # Include API routes
    app.include_router(health.router, tags=["health"])
    app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
    app.include_router(schema.router, prefix="/api/v1", tags=["schema"])
    app.include_router(queries.router, prefix="/api/v1", tags=["queries"])
    app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
    app.include_router(dml.router, prefix="/api/v1", tags=["dml"])
    app.include_router(data_dictionary.router, prefix="/api/v1", tags=["data-dictionary"])
    app.include_router(metrics.router, prefix="/api/v1", tags=["metrics"])
    app.include_router(consolidated.router, prefix="/api", tags=["consolidated"])

    return app


@pytest.fixture
def client(test_app):
    """Synchronous test client for FastAPI app with CSRF token"""
    from unittest.mock import patch

    # Bypass CSRF session verification in tests
    with patch('app.core.dependencies.verify_csrf_for_session', return_value=None):
        with TestClient(test_app) as c:
            yield c


@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables for testing"""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "none")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("APP_NAME", "QueryfyAI-Test")
