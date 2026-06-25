"""
QueryfyAI - Shared CSRF Utilities

This module provides centralized CSRF token verification functionality
to eliminate duplicate code across API files.
"""

import logging
from typing import Optional

from fastapi import Header, HTTPException

from app.services.security import AuditLogger, csrf_protection

logger = logging.getLogger(__name__)


async def verify_csrf_token(
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token")
) -> Optional[str]:
    """
    FastAPI dependency for CSRF token extraction and basic validation.

    Use this as a dependency in route handlers:
        @router.post("/endpoint")
        async def handler(csrf_token: Optional[str] = Depends(verify_csrf_token)):
            ...

    Returns:
        The CSRF token if present.
        Raises HTTPException(403) if token is missing.
    """
    if not x_csrf_token:
        logger.warning("CSRF token missing from request")
        raise HTTPException(status_code=403, detail="CSRF token required")

    return x_csrf_token


def verify_csrf_for_session(session_id: str, csrf_token: Optional[str]) -> None:
    """
    Verify CSRF token matches the session.

    This function should be called after extracting the token with verify_csrf_token
    to validate that the token belongs to the correct session.

    Args:
        session_id: The session ID to verify against
        csrf_token: The CSRF token from the request header

    Raises:
        HTTPException(403) if CSRF verification fails
    """
    if not csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token required")

    is_valid, msg = csrf_protection.verify_token(session_id, csrf_token)

    if not is_valid:
        logger.warning(f"CSRF verification failed: {msg}")
        AuditLogger.log_security_event(session_id, "CSRF_FAILED", msg)
        raise HTTPException(
            status_code=403, detail=f"CSRF verification failed: {msg}"
        )
