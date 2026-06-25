# ============================================
# FILE: app/api/sessions.py
# ============================================
import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.core.config import settings
from app.core.dependencies import get_session as get_session_validated
from app.core.logging_config import get_logger
from app.models.schemas import (
    ERROR_RESPONSES,
    CSRFTokenResponse,
    DatabaseConfig,
    DefaultConfigResponse,
    DefaultDBConfig,
    DefaultLLMConfig,
    LLMConfig,
    MessageResponse,
    SchemaStatusResponse,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
    TestConnectionResponse,
    TestLLMResponse,
    mask_connection_url,
)
from app.services.database_service import DatabaseService
from app.services.llm_service import LLMService
from app.services.security import (
    AuditLogger,
    QueryLanguageRegistry,
    csrf_protection,
    rate_limiter,
)
from app.services.session_store import session_store
from app.services.token_manager import token_manager
from app.services.vector_db import vector_db

router = APIRouter()
logger = get_logger(__name__)


async def validate_oauth_config(llm_config: LLMConfig) -> dict:
    """Validate OAuth configuration and get initial token"""
    if llm_config.provider != "oauth_gateway":
        return {"success": True, "message": "Not using OAuth"}

    # Validate required OAuth fields
    if not llm_config.token_url:
        return {"success": False, "message": "OAuth token_url is required"}
    if not llm_config.client_id:
        return {"success": False, "message": "OAuth client_id is required"}
    if not llm_config.client_secret:
        return {"success": False, "message": "OAuth client_secret is required"}
    if not llm_config.base_url:
        return {
            "success": False,
            "message": "LLM base_url is required for OAuth gateway",
        }

    # Try to get a token
    try:
        token = await token_manager.get_token(llm_config)
        if not token:
            return {
                "success": False,
                "message": "OAuth token request returned empty token",
            }
        return {"success": True, "message": "OAuth token obtained successfully"}
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            return {
                "success": False,
                "message": "OAuth authentication failed - check client_id and client_secret",
            }
        if "404" in error_msg:
            logger.error(f"OAuth token URL not found: {llm_config.token_url}")
            return {
                "success": False,
                "message": "OAuth token URL not found. Check your token_url configuration.",
            }
        if "connect" in error_msg.lower() or "timeout" in error_msg.lower():
            logger.error(f"Cannot reach OAuth server: {llm_config.token_url}: {error_msg}")
            return {
                "success": False,
                "message": "Cannot reach OAuth server. Check your token_url configuration.",
            }
        logger.error(f"OAuth token request failed: {error_msg}")
        return {"success": False, "message": "OAuth token request failed. Check your OAuth configuration."}


async def validate_llm_connection(
    llm_config: LLMConfig, db_type: str = "postgresql"
) -> dict:
    """Test LLM connection with a simple request"""
    try:
        # Simple test prompt - returns (sql, usage) tuple
        response, _ = await LLMService.generate_sql(
            llm_config,
            "Say 'OK' if you can hear me",
            "No schema - this is a connection test",
            [],
            db_type,
        )

        if response and len(response.strip()) > 0:
            return {"success": True, "message": "LLM connection verified"}
        else:
            return {"success": False, "message": "LLM returned empty response"}

    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to LLM endpoint - check base_url",
        }
    except httpx.TimeoutException:
        return {"success": False, "message": "LLM connection timed out"}
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            return {
                "success": False,
                "message": "LLM authentication failed - check API key or OAuth credentials",
            }
        if "404" in error_msg:
            return {
                "success": False,
                "message": "LLM endpoint not found - check base_url and chat_endpoint",
            }
        logger.error(f"LLM connection failed: {error_msg}")
        return {"success": False, "message": "LLM connection failed. Check your configuration."}


def merge_with_defaults(user_config: dict, default_config: dict) -> dict:
    """Merge user config with defaults. User values override defaults."""
    merged = default_config.copy()
    for key, value in user_config.items():
        # Only override if user provided a non-empty value
        if value is not None and value != "":
            merged[key] = value
    return merged


async def extract_schema_background(
    session_id: str, db_config: DatabaseConfig, llm_config: LLMConfig
):
    """
    Background task for schema extraction.
    Updates session state when complete.
    """
    try:
        logger.info(f"[Background] Extracting schema for session {session_id[:8]}...")

        # Extract schema
        schema = await DatabaseService.extract_schema(db_config)

        if schema.get("error"):
            logger.error(f"[Background] Schema extraction failed: {schema['error']}")
            session_store.update(
                session_id, {"schema_ready": False, "schema_error": schema["error"]}
            )
            return

        # Count both tables (SQL) and collections (MongoDB)
        table_count = len(schema.get("tables", []))
        collection_count = len(schema.get("collections", []))
        total_count = table_count + collection_count

        logger.info(
            f"[Background] Extracted schema: {table_count} tables, {collection_count} collections"
        )

        # Check if schema extraction actually returned anything
        if total_count == 0:
            # Schema extraction returned nothing - check if db_type is fully supported
            supported_types = QueryLanguageRegistry.get_supported_databases()
            if db_config.db_type in supported_types:
                error_msg = "No tables or collections found in database. Check database permissions and ensure the database is not empty."
            else:
                error_msg = f"Schema extraction not yet implemented for {db_config.db_type}. Supported types: {', '.join(supported_types)}"

            logger.warning(
                f"[Background] Empty schema for {db_config.db_type}: {error_msg}"
            )
            session_store.update(
                session_id,
                {
                    "schema_ready": False,
                    "schema_error": error_msg,
                    "schema_table_count": 0,
                },
            )
            return

        # Store in vector DB
        try:
            vector_db.store_schema(db_config.connection_url, schema)
            logger.info("[Background] Schema stored in vector database")
        except Exception as e:
            logger.warning(f"[Background] Failed to store schema in vector DB: {e}")

        # Cache schema if cache service available
        try:
            import hashlib

            from app.services.cache_service import cache_service

            db_hash = hashlib.sha256(db_config.connection_url.encode()).hexdigest()[:16]
            await cache_service.set_schema(
                db_hash, schema, ttl=settings.CACHE_TTL_SCHEMA
            )
        except Exception as e:
            logger.debug(f"[Background] Schema cache write skipped: {e}")

        # Update session with schema info
        session_store.update(
            session_id,
            {
                "schema": schema,
                "schema_ready": True,
                "schema_table_count": total_count,
                "schema_error": None,
            },
        )

        logger.info(
            f"[Background] Schema extraction complete for session {session_id[:8]}"
        )

    except Exception as e:
        logger.error(f"[Background] Schema extraction error: {e}")
        session_store.update(
            session_id, {"schema_ready": False, "schema_error": str(e)}
        )


@router.post(
    "/sessions",
    response_model=SessionResponse,
    responses={400: ERROR_RESPONSES[400], 429: ERROR_RESPONSES[429]},
)
async def create_session(
    session_request: SessionCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """Create a new session with LLM and DB configuration.

    This will:
    1. Rate limit check to prevent resource exhaustion
    2. Merge user config with server defaults (user values override)
    3. Validate the database connection URL
    4. Test the database connection
    5. Validate OAuth configuration (if using oauth_gateway)
    6. Test LLM connection
    7. Create the session
    8. Extract schema in background (non-blocking)
    """
    # Rate limiting to prevent resource exhaustion attacks
    client_ip = request.client.host if request.client else "unknown"
    allowed, rate_msg = rate_limiter.check_rate_limit(client_ip, "session_create")
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_msg)

    # Merge user config with defaults (user values take precedence)
    llm_defaults = settings.get_default_llm_config()
    db_defaults = settings.get_default_db_config()

    # Get user-provided config as dict
    user_llm = session_request.llm_config.model_dump()
    user_db = session_request.db_config.model_dump()

    # Merge configs (user values override defaults)
    merged_llm = merge_with_defaults(user_llm, llm_defaults)
    merged_db = merge_with_defaults(user_db, db_defaults)

    # Recreate config objects with merged values
    llm_config = LLMConfig(**merged_llm)
    db_config = DatabaseConfig(**merged_db)

    logger.info(
        f"Session config: LLM provider={llm_config.provider}, DB type={db_config.db_type}"
    )

    # Step 1: Validate connection URL format
    is_valid, error_msg = DatabaseService.validate_connection_url(
        db_config.db_type, db_config.connection_url
    )
    if not is_valid:
        raise HTTPException(
            status_code=400, detail=f"Invalid connection URL: {error_msg}"
        )

    # Step 2: Test database connection (quick validation)
    logger.info(f"Testing {db_config.db_type} connection...")
    test_result = await DatabaseService.test_connection(db_config)
    if not test_result["success"]:
        raise HTTPException(
            status_code=400,
            detail=f"Database connection failed: {test_result['message']}",
        )
    logger.info("✓ Database connection successful")

    # Step 3: Validate OAuth configuration (if using oauth_gateway)
    logger.info(f"Validating LLM configuration (provider: {llm_config.provider})...")
    oauth_result = await validate_oauth_config(llm_config)
    if not oauth_result["success"]:
        raise HTTPException(
            status_code=400,
            detail=f"OAuth validation failed: {oauth_result['message']}",
        )
    if llm_config.provider == "oauth_gateway":
        logger.info("✓ OAuth token obtained successfully")

    # Step 4: Test LLM connection
    logger.info("Testing LLM connection...")
    llm_result = await validate_llm_connection(llm_config, db_config.db_type)
    if not llm_result["success"]:
        raise HTTPException(
            status_code=400, detail=f"LLM connection failed: {llm_result['message']}"
        )
    logger.info("✓ LLM connection verified")

    # Step 5: Create session immediately
    session_id = session_store.create_session(
        llm_config.model_dump(), db_config.model_dump()
    )

    # Mark schema as loading
    session_store.update(session_id, {"schema_ready": False, "schema_error": None})

    # Store token info in session if using OAuth
    if llm_config.provider == "oauth_gateway":
        token_info = token_manager.get_token_info(llm_config)
        if token_info:
            session_store.update_token_info(session_id, token_info)

    # SECURITY: Generate CSRF token for the session
    csrf_token = csrf_protection.generate_token(session_id)

    # Step 6: Extract schema in background (non-blocking)
    background_tasks.add_task(
        extract_schema_background, session_id, db_config, llm_config
    )
    logger.info("✓ Schema extraction started in background")

    # Audit log session creation
    AuditLogger.log_session_event(
        session_id, "CREATED", f"DB: {db_config.db_type}, LLM: {llm_config.provider}"
    )

    # Compute connection hash for history filtering
    connection_hash = vector_db._hash_connection(db_config.connection_url)

    return SessionResponse(
        session_id=session_id,
        message="Session created. Schema loading in background...",
        locked=False,
        csrf_token=csrf_token,
        schema_ready=False,
        connection_hash=connection_hash,
        db_type=db_config.db_type,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetailResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_session(session_id: str) -> SessionDetailResponse:
    """Get session details (without sensitive config)"""
    # Session lookup using validated helper (raises 404 if not found)
    session = get_session_validated(session_id)

    return SessionDetailResponse(
        id=session["id"],
        created_at=session["created_at"],
        updated_at=session["updated_at"],
        locked=session["locked"],
        history_count=len(session.get("history", [])),
        db_type=session["db_config"].get("db_type"),
        llm_provider=session["llm_config"].get("provider"),
        token_info=session.get("token_info"),
        schema_ready=session.get("schema_ready", False),
        schema_table_count=session.get("schema_table_count", 0),
        schema_error=session.get("schema_error"),
    )


@router.get(
    "/sessions/{session_id}/schema-status",
    response_model=SchemaStatusResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_schema_status(session_id: str) -> SchemaStatusResponse:
    """
    Get schema extraction status for a session.

    Use this endpoint to poll for schema readiness after session creation.
    """
    # Session lookup using validated helper (raises 404 if not found)
    session = get_session_validated(session_id)

    schema_ready = session.get("schema_ready", False)
    schema_error = session.get("schema_error")
    table_count = session.get("schema_table_count", 0)

    return SchemaStatusResponse(
        session_id=session_id,
        schema_ready=schema_ready,
        table_count=table_count,
        error=schema_error,
        message=(
            f"Schema ready with {table_count} tables"
            if schema_ready
            else (
                "Schema extraction failed"
                if schema_error
                else "Schema extraction in progress..."
            )
        ),
    )


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
async def delete_session(session_id: str) -> MessageResponse:
    """Delete a session and clean up security data"""
    from app.services.result_cache import result_cache
    from app.services.security import rate_limiter, sql_integrity

    # Clean up security services
    sql_integrity.cleanup_session(session_id)
    rate_limiter.cleanup_session(session_id)
    csrf_protection.cleanup_session(session_id)

    # Security hotfix: purge cached query results so rows don't
    # survive for up to RESULT_CACHE_TTL_SECONDS (30 min) past
    # session deletion. Combined with the GET /results/{rows_ref}
    # IDOR fix, this closes the PII-persistence window — a leaked
    # session_id for a deleted session can no longer read data.
    purged = result_cache.delete_session(session_id)
    if purged:
        logger.info(
            "Session delete purged %d cached result(s) for %s",
            purged,
            session_id[:8],
        )

    # Audit log session end
    AuditLogger.log_session_event(session_id, "DELETED")

    session_store.delete(session_id)
    return MessageResponse(message="Session deleted")


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(limit: int = 50) -> SessionListResponse:
    """List all sessions"""
    from app.models.schemas import SessionInfo

    session_dicts = session_store.list_sessions(limit)
    sessions = [SessionInfo(**session) for session in session_dicts]
    return SessionListResponse(sessions=sessions)


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_db_connection(config: DatabaseConfig):
    """Test database connection"""
    result = await DatabaseService.test_connection(config)
    return TestConnectionResponse(**result)


@router.post("/test-llm", response_model=TestLLMResponse)
async def test_llm_connection(config: LLMConfig, db_type: str = "postgresql"):
    """Test LLM connection"""
    try:
        # Returns (sql, usage) tuple
        response, _ = await LLMService.generate_sql(
            config,
            "Say 'connected' if you can hear me",
            "No schema needed",
            [],
            db_type,
        )
        return TestLLMResponse(
            success=True,
            message="LLM connected successfully",
            response_preview=response[:200] if response else "",
        )
    except Exception as e:
        return TestLLMResponse(success=False, message=str(e))


@router.get(
    "/sessions/{session_id}/csrf-token",
    response_model=CSRFTokenResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_csrf_token(session_id: str) -> CSRFTokenResponse:
    """Get a new CSRF token for the session"""
    # Session lookup using validated helper (raises 404 if not found)
    get_session_validated(session_id)

    csrf_token = csrf_protection.generate_token(session_id)
    return CSRFTokenResponse(csrf_token=csrf_token)


@router.get("/config/defaults", response_model=DefaultConfigResponse)
async def get_default_config():
    """Get default LLM and database configuration.

    Returns pre-configured defaults from environment variables.
    Sensitive fields (secrets, API keys) are masked - only their presence is indicated.
    Frontend should use these defaults and allow users to override them.
    """
    llm_defaults = settings.get_default_llm_config()
    db_defaults = settings.get_default_db_config()

    # Create response with masked sensitive fields
    llm_config = DefaultLLMConfig(
        provider=llm_defaults["provider"],
        base_url=llm_defaults["base_url"],
        token_url=llm_defaults["token_url"],
        client_id=llm_defaults["client_id"],
        client_secret_set=bool(settings.DEFAULT_LLM_CLIENT_SECRET),
        auth_scope=llm_defaults["auth_scope"],
        auth_type=llm_defaults["auth_type"],
        tenant=llm_defaults["tenant"],
        star=llm_defaults["star"],
        chat_endpoint=llm_defaults["chat_endpoint"],
        api_key_set=bool(settings.DEFAULT_LLM_API_KEY),
        model=llm_defaults["model"],
    )

    raw_connection_url = db_defaults["connection_url"]
    db_config = DefaultDBConfig(
        db_type=db_defaults["db_type"],
        connection_url=mask_connection_url(raw_connection_url),
        connection_url_set=bool(raw_connection_url),
        name=db_defaults["name"],
    )

    return DefaultConfigResponse(
        has_defaults=settings.has_default_llm_config(),
        llm_config=llm_config,
        db_config=db_config,
    )
