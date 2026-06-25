"""
Shared fixtures for integration tests.
"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_llm_config():
    """Sample LLM configuration"""
    from app.models.schemas import LLMConfig
    return LLMConfig(
        provider="openai",
        model="gpt-4",
        api_key="test-key"
    )


@pytest.fixture
def mock_db_config():
    """Sample database configuration"""
    from app.models.schemas import DatabaseConfig
    return DatabaseConfig(
        connection_url="postgresql://test:test@localhost/testdb",
        db_type="postgresql"
    )


@pytest.fixture(autouse=True)
def mock_agent_session_store():
    """Mock session_store and checkpointer for agent tests.

    ReActAgent.__init__ calls session_store.get() and session_store.update()
    directly, so we need to mock these at the react_agent module level.
    """
    from app.core.config import settings
    mock_store = MagicMock()
    mock_store.get.return_value = {
        "session_id": "test-session",
        "llm_config": {"provider": "openai", "model": "gpt-4", "api_key": "test-key"},
        "db_config": {"connection_url": "postgresql://test:test@localhost/testdb", "db_type": "postgresql"},
        "schema_ready": True,
        "conversation_thread_id": None,
    }
    mock_store.update.return_value = None

    with patch('app.services.react_agent.session_store', mock_store), \
         patch('app.services.react_agent.get_checkpointer', return_value=None), \
         patch.object(settings, "DEVELOPMENT_MODE", True):
        yield mock_store
