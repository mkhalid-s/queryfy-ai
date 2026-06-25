"""
QueryfyAI - DML API Endpoints

Endpoints for Data Modification Language operations:
- POST /api/dml/preview - Preview what DML would do
- POST /api/dml/execute - Execute DML in sandbox or confirm mode
- POST /api/dml/request-confirmation - Get confirmation token for DML
"""

from typing import Any, Dict, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.csrf_utils import verify_csrf_for_session, verify_csrf_token
from app.core.dependencies import get_session as get_session_validated
from app.core.logging_config import get_logger
from app.models.schemas import (
    ERROR_RESPONSES,
    DatabaseConfig,
    DMLConfirmationRequest,
    DMLConfirmationResponse,
    DMLExecuteRequest,
    DMLExecuteResponse,
    DMLMode,
    DMLPreviewResult,
)
from app.services.dml_service import DML_CAPABILITIES, DMLService
from app.services.security import (
    AuditLogger,
    ErrorSanitizer,
    SecurityService,
    rate_limiter,
)

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "/dml/preview",
    response_model=DMLPreviewResult,
    responses={400: ERROR_RESPONSES[400], 404: ERROR_RESPONSES[404]},
)
async def preview_dml(
    session_id: str,
    sql: str,
    request: Request,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> DMLPreviewResult:
    """
    Preview what a DML statement would do without executing.

    Returns estimated rows affected and sample data for UPDATE/DELETE.
    For INSERT, shows the data that would be inserted.

    Args:
        session_id: Session ID
        sql: DML SQL statement to preview
        request: FastAPI request object
        csrf_token: CSRF token from request header

    Returns:
        DMLPreviewResult with operation details and warnings
    """
    # Validate session
    session = get_session_validated(session_id)

    # Verify CSRF
    verify_csrf_for_session(session_id, csrf_token)

    # Get DB config
    db_config = DatabaseConfig(**session["db_config"])

    # Validate DML (preview mode allows DML for preview purposes)
    is_valid, error_msg = SecurityService.validate_dml_sql(sql, DMLMode.PREVIEW.value)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Audit log - use security event for DML operations
    AuditLogger.log_security_event(session_id, "DML_PREVIEW", f"SQL: {sql[:500]}")

    try:
        result = await DMLService.preview_dml(db_config, sql)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=ErrorSanitizer.sanitize_error(e))
    except Exception:
        logger.exception("DML preview error")
        raise HTTPException(status_code=500, detail="DML preview failed. Please try again.")


@router.post(
    "/dml/execute",
    response_model=DMLExecuteResponse,
    responses={
        400: ERROR_RESPONSES[400],
        404: ERROR_RESPONSES[404],
        428: {"description": "Confirmation required - returns confirmation token"},
        429: ERROR_RESPONSES[429],
    },
)
async def execute_dml(
    request_body: DMLExecuteRequest,
    request: Request,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> Union[DMLExecuteResponse, JSONResponse]:
    """
    Execute a DML statement based on the specified mode.

    Modes:
    - SANDBOX: Execute and rollback (no permanent changes)
    - CONFIRM: Execute with confirmation token (permanent changes)

    For CONFIRM mode:
    - First call without token: Returns 428 with confirmation token
    - Second call with token: Executes and commits the DML

    Args:
        request_body: DMLExecuteRequest with session_id, sql, mode, and optional token
        request: FastAPI request object

    Returns:
        DMLExecuteResponse with execution results
    """
    # Validate session
    session = get_session_validated(request_body.session_id)

    # Verify CSRF
    verify_csrf_for_session(request_body.session_id, csrf_token)

    # Rate limiting for DML (use session_id to avoid issues with shared IPs like NAT/VPN)
    allowed, msg = rate_limiter.check_rate_limit(request_body.session_id, "query")
    if not allowed:
        raise HTTPException(status_code=429, detail=msg)

    # Get DB config
    db_config = DatabaseConfig(**session["db_config"])

    # Validate DML
    is_valid, error_msg = SecurityService.validate_dml_sql(
        request_body.sql, request_body.mode.value
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Handle different modes
    if request_body.mode == DMLMode.DISABLED:
        raise HTTPException(
            status_code=400,
            detail="DML operations are disabled. Enable preview, sandbox, or confirm mode.",
        )

    elif request_body.mode == DMLMode.PREVIEW:
        # Preview mode should use /dml/preview endpoint
        raise HTTPException(
            status_code=400, detail="Use /dml/preview endpoint for preview mode"
        )

    elif request_body.mode == DMLMode.SANDBOX:
        # Audit log - use security event for DML operations
        AuditLogger.log_security_event(
            request_body.session_id, "DML_SANDBOX", f"SQL: {request_body.sql[:500]}"
        )

        try:
            result = await DMLService.execute_sandbox(db_config, request_body.sql)
            return DMLExecuteResponse(**result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=ErrorSanitizer.sanitize_error(e))
        except Exception:
            logger.exception("DML sandbox error")
            raise HTTPException(
                status_code=500, detail="Sandbox execution failed. Please try again."
            )

    elif request_body.mode == DMLMode.CONFIRM:
        # Check for confirmation token
        if not request_body.confirmation_token:
            # First call - generate token and return 428
            token = await DMLService.generate_confirmation_token(
                request_body.session_id, request_body.sql
            )
            # Return 428 Precondition Required with confirmation token
            return JSONResponse(
                status_code=428,
                content={
                    "message": "Confirmation required. Use the provided token to confirm execution.",
                    "confirmation_token": token,
                    "expires_in_seconds": 300,
                },
            )

        # Second call - validate token and execute
        if not await DMLService.validate_confirmation_token(
            request_body.confirmation_token, request_body.session_id, request_body.sql
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired confirmation token. Request a new token.",
            )

        # Audit log (confirmed execution) - use security event for DML operations
        AuditLogger.log_security_event(
            request_body.session_id, "DML_EXECUTE", f"SQL: {request_body.sql[:500]}"
        )

        try:
            result = await DMLService.execute_confirmed(db_config, request_body.sql)
            return DMLExecuteResponse(**result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=ErrorSanitizer.sanitize_error(e))
        except Exception:
            logger.exception("DML execute error")
            raise HTTPException(status_code=500, detail="DML execution failed. Please try again.")

    else:
        raise HTTPException(
            status_code=400, detail=f"Invalid DML mode: {request_body.mode}"
        )


@router.post(
    "/dml/request-confirmation",
    response_model=DMLConfirmationResponse,
    responses={400: ERROR_RESPONSES[400], 404: ERROR_RESPONSES[404]},
)
async def request_dml_confirmation(
    request_body: DMLConfirmationRequest,
    request: Request,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> DMLConfirmationResponse:
    """
    Request a confirmation token for DML execution.

    The token is:
    - Valid for 5 minutes
    - Single-use (deleted after validation)
    - Bound to specific session and SQL

    Args:
        request_body: DMLConfirmationRequest with session_id and sql
        request: FastAPI request object

    Returns:
        DMLConfirmationResponse with token and expiry info
    """
    # Validate session
    get_session_validated(request_body.session_id)

    # Verify CSRF
    verify_csrf_for_session(request_body.session_id, csrf_token)

    # Validate DML
    is_valid, error_msg = SecurityService.validate_dml_sql(
        request_body.sql, DMLMode.CONFIRM.value
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Generate token
    token = await DMLService.generate_confirmation_token(
        request_body.session_id, request_body.sql
    )

    return DMLConfirmationResponse(
        confirmation_token=token,
        expires_in_seconds=300,
        message="Token generated. Use this token within 5 minutes to confirm DML execution.",
    )


@router.get(
    "/dml/capabilities/{db_type}",
    response_model=Dict[str, Any],
    responses={404: ERROR_RESPONSES[404]},
)
async def get_dml_capabilities(db_type: str) -> Dict[str, Any]:
    """
    Get DML capabilities for a specific database type.

    Returns information about:
    - Supported DML modes (preview, sandbox, confirm)
    - Transaction support
    - Any warnings or limitations

    Args:
        db_type: Database type (postgresql, mysql, sqlite, mongodb, etc.)

    Returns:
        Dict with modes, has_transactions, notes, warning, blocked
    """
    caps = DMLService.get_capabilities(db_type)

    if not caps.get("modes") and not caps.get("blocked"):
        raise HTTPException(status_code=404, detail=f"Unknown database type: {db_type}")

    return {"db_type": db_type.lower(), **caps}


@router.get("/dml/capabilities", response_model=Dict[str, Dict[str, Any]])
async def list_dml_capabilities() -> Dict[str, Dict[str, Any]]:
    """
    List DML capabilities for all supported database types.

    Returns a map of database types to their DML capabilities.

    This endpoint is useful for:
    - Building UI that shows which DML modes are available
    - Validating database support before enabling DML features
    - Understanding limitations of each database type

    Returns:
        Dict mapping database types to their capabilities
    """
    return DML_CAPABILITIES
