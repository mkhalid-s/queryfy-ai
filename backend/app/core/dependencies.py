"""
QueryfyAI - Shared API Dependencies

Provides reusable FastAPI dependencies for common validation patterns:
- Session lookup and validation
- CSRF token verification
- Rate limiting

This eliminates ~15 lines of repeated validation code per endpoint.
"""

from typing import Callable, Optional

from fastapi import Depends, HTTPException

from app.core.csrf_utils import verify_csrf_for_session, verify_csrf_token
from app.core.logging_config import get_logger
from app.services.security import AuditLogger, ErrorSanitizer, rate_limiter
from app.services.session_store import session_store

logger = get_logger(__name__)


class SessionValidationResult:
    """Container for session validation result with convenient access."""

    def __init__(
        self, session: dict, session_id: str, csrf_token: Optional[str] = None
    ):
        self.session = session
        self.session_id = session_id
        self.csrf_token = csrf_token

    @property
    def llm_config(self) -> dict:
        """Get LLM config from session."""
        return self.session.get("llm_config", {})

    @property
    def db_config(self) -> dict:
        """Get DB config from session."""
        return self.session.get("db_config", {})

    @property
    def is_locked(self) -> bool:
        """Check if session is locked."""
        return self.session.get("locked", False)

    @property
    def schema_ready(self) -> bool:
        """Check if schema is ready."""
        return self.session.get("schema_ready", False)

    @property
    def schema_error(self) -> Optional[str]:
        """Get schema error if any."""
        return self.session.get("schema_error")


def get_session(session_id: str) -> dict:
    """
    Get session by ID or raise 404.

    This is the core session lookup used by all validation dependencies.

    Args:
        session_id: Session identifier

    Returns:
        Session dictionary

    Raises:
        HTTPException(404): If session not found
    """
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def check_rate_limit(session_id: str, action: str) -> None:
    """
    Check rate limit for action or raise 429.

    Args:
        session_id: Session identifier for rate limit tracking
        action: Rate limit action type ('generate', 'execute', 'export', 'followup')

    Raises:
        HTTPException(429): If rate limit exceeded
    """
    allowed, rate_msg = rate_limiter.check_rate_limit(session_id, action)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_msg)


def create_session_validator(
    require_csrf: bool = True,
    rate_limit_action: Optional[str] = None,
    require_schema_ready: bool = False,
    require_unlocked: bool = False,
) -> Callable:
    """
    Factory for creating session validation dependencies with specific requirements.

    This allows creating custom validators for different endpoint needs:
    - Full validation (CSRF + rate limit)
    - Session only (GET endpoints)
    - Session + CSRF (no rate limit)

    Args:
        require_csrf: Whether to verify CSRF token (default: True)
        rate_limit_action: Action type for rate limiting, None to skip
        require_schema_ready: Whether to require schema to be ready
        require_unlocked: Whether to require session to be unlocked

    Returns:
        A FastAPI dependency function

    Example:
        # Create validator for generate endpoint
        validate_generate = create_session_validator(
            require_csrf=True,
            rate_limit_action='generate',
            require_schema_ready=True
        )

        @router.post("/query/generate")
        async def generate(
            request: QueryRequest,
            validated: SessionValidationResult = Depends(validate_generate)
        ):
            session = validated.session
            ...
    """

    async def validator(
        session_id: str, csrf_token: Optional[str] = Depends(verify_csrf_token)
    ) -> SessionValidationResult:
        # 1. Session lookup (always required)
        session = get_session(session_id)

        # 2. CSRF verification (optional)
        if require_csrf:
            verify_csrf_for_session(session_id, csrf_token)

        # 3. Rate limiting (optional)
        if rate_limit_action:
            check_rate_limit(session_id, rate_limit_action)

        # 4. Schema ready check (optional)
        if require_schema_ready:
            schema_ready = session.get("schema_ready", False)
            schema_error = session.get("schema_error")

            if schema_error:
                raise HTTPException(
                    status_code=400,
                    detail=f"Schema extraction failed: {schema_error}. Please reconnect to the database.",
                )

            if not schema_ready:
                raise HTTPException(
                    status_code=400,
                    detail="Schema is still loading. Please wait a moment and try again.",
                )

        # 5. Unlocked check (optional)
        if require_unlocked:
            if session.get("locked", False):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot perform this operation on a locked session",
                )

        return SessionValidationResult(session, session_id, csrf_token)

    return validator


# ============================================
# Direct validation function for body-based session_id
# ============================================


def validate_request(
    session_id: str,
    csrf_token: Optional[str],
    rate_limit_action: Optional[str] = None,
    require_schema_ready: bool = False,
    require_unlocked: bool = False,
    require_csrf: bool = True,
) -> dict:
    """
    Validate request and return session dict.

    Use this for endpoints where session_id comes from request body
    rather than path/query parameters.

    Args:
        session_id: Session identifier from request body
        csrf_token: CSRF token from header (via Depends(verify_csrf_token))
        rate_limit_action: Action type for rate limiting ('generate', 'execute', 'export', 'followup')
        require_schema_ready: If True, raises 400 if schema not ready
        require_unlocked: If True, raises 400 if session is locked
        require_csrf: If True, verifies CSRF token

    Returns:
        Session dictionary

    Raises:
        HTTPException(404): Session not found
        HTTPException(403): CSRF verification failed
        HTTPException(429): Rate limit exceeded
        HTTPException(400): Schema not ready or session locked

    Example:
        @router.post("/query/generate")
        async def generate(
            request: QueryRequest,
            csrf_token: Optional[str] = Depends(verify_csrf_token)
        ):
            session = validate_request(
                request.session_id,
                csrf_token,
                rate_limit_action='generate',
                require_schema_ready=True
            )
            # ... use session ...
    """
    # 1. Session lookup (always required)
    session = get_session(session_id)

    # 2. CSRF verification
    if require_csrf:
        verify_csrf_for_session(session_id, csrf_token)

    # 3. Rate limiting
    if rate_limit_action:
        check_rate_limit(session_id, rate_limit_action)

    # 4. Schema ready check
    if require_schema_ready:
        schema_error = session.get("schema_error")
        if schema_error:
            raise HTTPException(
                status_code=400,
                detail=f"Schema extraction failed: {schema_error}. Please reconnect to the database.",
            )
        if not session.get("schema_ready", False):
            raise HTTPException(
                status_code=400,
                detail="Schema is still loading. Please wait a moment and try again.",
            )

    # 5. Unlocked check
    if require_unlocked:
        if session.get("locked", False):
            raise HTTPException(
                status_code=400,
                detail="Cannot perform this operation on a locked session",
            )

    return session


# ============================================
# Pre-configured validators for common patterns
# ============================================

# For query generation endpoints (most restrictive)
validate_for_generate = create_session_validator(
    require_csrf=True, rate_limit_action="generate", require_schema_ready=True
)

# For query execution endpoints
validate_for_execute = create_session_validator(
    require_csrf=True, rate_limit_action="execute"
)

# For query export endpoints
validate_for_export = create_session_validator(
    require_csrf=True, rate_limit_action="export"
)

# For follow-up endpoints
validate_for_followup = create_session_validator(
    require_csrf=True, rate_limit_action="followup"
)

# For explain endpoints (uses 'generate' rate limit)
validate_for_explain = create_session_validator(
    require_csrf=True, rate_limit_action="generate"
)

# For schema operations (CSRF but no rate limit)
validate_for_schema = create_session_validator(
    require_csrf=True, rate_limit_action=None, require_unlocked=True
)

# For read-only session operations (no CSRF, no rate limit)
validate_session_only = create_session_validator(
    require_csrf=False, rate_limit_action=None
)


# ============================================
# Helper for extracting session_id from request body
# ============================================


class RequestSessionValidator:
    """
    Validator that extracts session_id from request body instead of path/query.

    Usage:
        @router.post("/query/generate")
        async def generate(
            request: QueryRequest,
            validated: SessionValidationResult = Depends(
                RequestSessionValidator(rate_limit_action='generate', require_schema_ready=True)
            )
        ):
            # validated.session is available
    """

    def __init__(
        self,
        require_csrf: bool = True,
        rate_limit_action: Optional[str] = None,
        require_schema_ready: bool = False,
        require_unlocked: bool = False,
    ):
        self.require_csrf = require_csrf
        self.rate_limit_action = rate_limit_action
        self.require_schema_ready = require_schema_ready
        self.require_unlocked = require_unlocked

    async def __call__(
        self,
        request,  # Will be the Pydantic model with session_id
        csrf_token: Optional[str] = Depends(verify_csrf_token),
    ) -> SessionValidationResult:
        # Extract session_id from request body
        session_id = getattr(request, "session_id", None)
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")

        # 1. Session lookup
        session = get_session(session_id)

        # 2. CSRF verification
        if self.require_csrf:
            verify_csrf_for_session(session_id, csrf_token)

        # 3. Rate limiting
        if self.rate_limit_action:
            check_rate_limit(session_id, self.rate_limit_action)

        # 4. Schema ready check
        if self.require_schema_ready:
            schema_ready = session.get("schema_ready", False)
            schema_error = session.get("schema_error")

            if schema_error:
                raise HTTPException(
                    status_code=400,
                    detail=f"Schema extraction failed: {schema_error}. Please reconnect to the database.",
                )

            if not schema_ready:
                raise HTTPException(
                    status_code=400,
                    detail="Schema is still loading. Please wait a moment and try again.",
                )

        # 5. Unlocked check
        if self.require_unlocked:
            if session.get("locked", False):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot perform this operation on a locked session",
                )

        return SessionValidationResult(session, session_id, csrf_token)


# ============================================
# Error Handler Utilities
# ============================================


def raise_server_error(e: Exception, context: str = "operation") -> None:
    """
    Raise a 500 Internal Server Error with sanitized message.

    Args:
        e: The exception that occurred
        context: Description of what was happening (for logging)

    Raises:
        HTTPException(500): Always raises this exception

    Example:
        try:
            await some_operation()
        except Exception as e:
            logger.error(f"Operation failed: {ErrorSanitizer.safe_log_error(e)}")
            raise_server_error(e, "SQL generation")
    """
    raise HTTPException(status_code=500, detail=ErrorSanitizer.sanitize_error(e))


def raise_validation_error(e: Exception) -> None:
    """
    Raise a 400 Bad Request with sanitized message.

    Args:
        e: The exception that occurred

    Raises:
        HTTPException(400): Always raises this exception
    """
    raise HTTPException(status_code=400, detail=ErrorSanitizer.sanitize_error(e))


def raise_security_error(
    session_id: str, event_type: str, message: str, details: str = ""
) -> None:
    """
    Raise a 403 Forbidden error and log the security event.

    Args:
        session_id: Session identifier for audit logging
        event_type: Type of security event (e.g., "SQL_VERIFICATION_FAILED")
        message: User-facing error message
        details: Additional details for audit log (not exposed to user)

    Raises:
        HTTPException(403): Always raises this exception

    Example:
        if not is_verified:
            raise_security_error(
                session_id,
                "SQL_VERIFICATION_FAILED",
                f"Security check failed: {verify_msg}",
                f"SQL: {request.sql_query[:100]}..."
            )
    """
    AuditLogger.log_security_event(session_id, event_type, details)
    raise HTTPException(status_code=403, detail=message)


def safe_log_error(e: Exception) -> str:
    """
    Get a safe error message for logging (no sensitive data).

    Args:
        e: The exception

    Returns:
        Sanitized error string safe for logging

    Example:
        logger.error(f"Operation failed: {safe_log_error(e)}")
    """
    return ErrorSanitizer.safe_log_error(e)
