"""
QueryfyAI - Consolidated API Schemas

Pydantic models for consolidated endpoints that reduce API calls.
See: BACKEND-API-CONSOLIDATION.md
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.schemas import (
    DefaultDBConfig,
    DefaultLLMConfig,
    ExecuteQueryResponse,
    HistoryEntry,
)

# ============== Init Endpoint ==============


class InitRequest(BaseModel):
    """Request for /init endpoint"""

    previous_session_id: Optional[str] = None


class SessionSummary(BaseModel):
    """Summary of session info (non-sensitive)"""

    id: str
    locked: bool = False
    db_type: str
    llm_provider: str
    created_at: str = ""
    updated_at: str = ""
    connection_hash: Optional[str] = (
        None  # For history filtering by database connection
    )


class InitResponse(BaseModel):
    """Response from /init endpoint - all data needed on app start"""

    # Default configuration
    has_defaults: bool
    llm_config: DefaultLLMConfig
    db_config: DefaultDBConfig

    # Restored session (if previous_session_id was valid)
    session: Optional[SessionSummary] = None
    history: List[HistoryEntry] = []
    csrf_token: Optional[str] = None
    token_info: Optional[Dict[str, Any]] = None


# ============== Extended Query Generate ==============


class QueryGenerateExtendedRequest(BaseModel):
    """Extended query generation request with optional auto-execute"""

    session_id: str
    natural_language: str = Field(..., min_length=3, max_length=5000)

    # New: Auto-execute options
    auto_execute: bool = False
    execute_limit: int = Field(default=100, ge=1, le=1000)


class QueryGenerateExtendedResponse(BaseModel):
    """Extended response including history and optional execution results"""

    # Standard generation response
    sql: Optional[str] = None
    query_id: Optional[str] = None
    sql_hash: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None
    warnings: Optional[List[str]] = None
    usage: Optional[Dict[str, Any]] = None  # LLM token usage and cost data

    # New: Include updated history
    history: Optional[List[HistoryEntry]] = None

    # New: Auto-execution results
    executed: bool = False
    execution_result: Optional[ExecuteQueryResponse] = None
    execution_error: Optional[str] = None


# ============== Batch Actions ==============


class BatchAction(BaseModel):
    """Single action in a batch request"""

    type: Literal["explain", "feedback"]
    params: Optional[Dict[str, Any]] = None
    # For feedback: {"rating": 1-5, "comment": str}


class BatchActionRequest(BaseModel):
    """Request for batch query actions"""

    session_id: str
    query_id: Optional[str] = None
    sql_query: str = Field(..., min_length=10, max_length=50000)
    sql_hash: Optional[str] = None
    actions: List[BatchAction] = Field(..., min_length=1, max_length=10)


class ActionResult(BaseModel):
    """Result of a single batch action"""

    type: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BatchActionResponse(BaseModel):
    """Response from batch actions endpoint"""

    results: List[ActionResult]


# ============== Session Restore ==============


class RestoreSessionResponse(BaseModel):
    """Response from session restore endpoint"""

    session: SessionSummary
    history: List[HistoryEntry] = []
    csrf_token: Optional[str] = None
    token_info: Optional[Dict[str, Any]] = None
