# ============================================
# FILE: app/api/schema.py
# ============================================
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.core.csrf_utils import verify_csrf_token
from app.core.dependencies import get_session, validate_request
from app.core.logging_config import get_logger
from app.models.schemas import (
    ERROR_RESPONSES,
    DatabaseConfig,
    DebugSchemaResponse,
    EmbeddingTestResponse,
    RefreshSchemaResponse,
    SchemaResponse,
    VectorDBSearchResponse,
    VectorDBStatsResponse,
)
from app.services.database_service import DatabaseService
from app.services.session_store import session_store
from app.services.vector_db import vector_db

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "/schema/refresh",
    response_model=RefreshSchemaResponse,
    responses={400: ERROR_RESPONSES[400], 404: ERROR_RESPONSES[404]},
)
async def refresh_schema(
    session_id: str,
    background_tasks: BackgroundTasks,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> RefreshSchemaResponse:
    """Refresh database schema (background task)"""
    # Consolidated validation: session lookup, CSRF, require unlocked
    session = validate_request(
        session_id, csrf_token, require_csrf=True, require_unlocked=True
    )

    db_config = DatabaseConfig(**session["db_config"])

    async def refresh_task():
        try:
            schema = await DatabaseService.extract_schema(db_config)
            vector_db.store_schema(db_config.connection_url, schema)
        except Exception as e:
            logger.error("Schema refresh error", error=str(e))

    background_tasks.add_task(refresh_task)
    return RefreshSchemaResponse(message="Schema refresh started", status="processing")


# ============ Debug/Diagnostic Endpoints (before parameterized routes) ============


@router.get("/schema/vector-db/stats", response_model=VectorDBStatsResponse)
async def get_vector_db_stats() -> VectorDBStatsResponse:
    """
    Get vector database statistics and loaded schemas.
    Useful for debugging schema loading issues.
    """
    collections = {}
    loaded_schemas = []
    error = None

    try:
        if vector_db.db_type == "chromadb":
            # Get ChromaDB stats
            schema_count = vector_db.schema_collection.count()
            query_count = vector_db.query_collection.count()

            collections = {
                "schema_embeddings": schema_count,
                "query_history": query_count,
            }

            # Get unique connection hashes (databases)
            if schema_count > 0:
                all_items = vector_db.schema_collection.get(include=["metadatas"])
                tables_by_db: Dict[str, List[str]] = {}

                for metadata in all_items.get("metadatas", []):
                    conn_hash = metadata.get("connection_hash", "unknown")
                    table_name = metadata.get("name", "unknown")

                    if conn_hash not in tables_by_db:
                        tables_by_db[conn_hash] = []
                    tables_by_db[conn_hash].append(table_name)

                from app.models.schemas import LoadedSchemaInfo

                loaded_schemas = [
                    LoadedSchemaInfo(
                        connection_hash=conn_hash,
                        table_count=len(tables),
                        tables=sorted(set(tables))[:20],
                        truncated=len(tables) > 20,
                    )
                    for conn_hash, tables in tables_by_db.items()
                ]

        elif vector_db.db_type == "qdrant":
            # Get Qdrant stats
            schema_info = vector_db.client.get_collection("schema_embeddings")
            query_info = vector_db.client.get_collection("query_history")

            collections = {
                "schema_embeddings": schema_info.points_count,
                "query_history": query_info.points_count,
                "vector_size": schema_info.config.params.vectors.size,
            }

            # Get unique connection hashes
            if schema_info.points_count > 0:
                points, _ = vector_db.client.scroll(
                    collection_name="schema_embeddings",
                    limit=1000,
                    with_payload=True,
                    with_vectors=False,
                )

                tables_by_db = {}
                for point in points:
                    conn_hash = point.payload.get("connection_hash", "unknown")
                    table_name = point.payload.get("name", "unknown")

                    if conn_hash not in tables_by_db:
                        tables_by_db[conn_hash] = []
                    tables_by_db[conn_hash].append(table_name)

                from app.models.schemas import LoadedSchemaInfo

                loaded_schemas = [
                    LoadedSchemaInfo(
                        connection_hash=conn_hash,
                        table_count=len(set(tables)),
                        tables=sorted(set(tables))[:20],
                        truncated=len(tables) > 20,
                    )
                    for conn_hash, tables in tables_by_db.items()
                ]

    except Exception as e:
        logger.error("Error getting vector DB stats", error=str(e))
        error = str(e)

    return VectorDBStatsResponse(
        db_type=vector_db.db_type,
        embedding_enabled=vector_db.embedding_fn is not None,
        collections=collections,
        loaded_schemas=loaded_schemas,
        error=error,
    )


@router.get("/schema/test-embedding", response_model=EmbeddingTestResponse)
async def test_embedding() -> EmbeddingTestResponse:
    """Test if embedding generation is working"""
    test_query = "show all customers"
    embedding_generated = False
    embedding_dimension = None
    error = None

    if not vector_db.embedding_fn:
        error = "No embedding function configured"
    else:
        try:
            embeddings = vector_db._generate_embeddings([test_query])
            if embeddings:
                embedding_generated = True
                embedding_dimension = len(embeddings[0])
            else:
                error = "Embedding function returned None"
        except Exception as e:
            error = str(e)

    return EmbeddingTestResponse(
        embedding_enabled=vector_db.embedding_fn is not None,
        test_query=test_query,
        embedding_generated=embedding_generated,
        embedding_dimension=embedding_dimension,
        error=error,
    )


@router.get(
    "/schema/vector-db/search",
    response_model=VectorDBSearchResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def search_vector_db(
    query: str, session_id: Optional[str] = None
) -> VectorDBSearchResponse:
    """
    Search vector DB for schema matching a query.
    Useful for debugging why certain tables aren't found.
    """
    connection_url = None
    connection_hash = None
    schema_text = None
    schema_found = None
    message = None
    error = None

    if session_id:
        session = session_store.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        db_config = DatabaseConfig(**session["db_config"])
        connection_url = db_config.connection_url

    try:
        if connection_url:
            connection_hash = vector_db._hash_connection(connection_url)
            schema_text = vector_db.get_relevant_schema(
                connection_url, query, max_items=10
            )
            schema_found = "No schema information available" not in schema_text
        else:
            message = "Provide session_id to search within a specific database"

    except Exception as e:
        logger.error("Vector DB search error", error=str(e))
        error = str(e)

    return VectorDBSearchResponse(
        query=query,
        connection_url_provided=connection_url is not None,
        matches=[],
        connection_hash=connection_hash,
        schema_text=schema_text,
        schema_found=schema_found,
        message=message,
        error=error,
    )


@router.get(
    "/schema/debug/{session_id}",
    response_model=DebugSchemaResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def debug_schema_lookup(session_id: str) -> DebugSchemaResponse:
    """
    Debug schema lookup for a session.
    Shows connection hash comparison and stored vs queried hash.
    """
    # Session lookup only (no CSRF for GET, no rate limit for debug)
    session = get_session(session_id)

    db_config = DatabaseConfig(**session["db_config"])
    conn_hash = vector_db._hash_connection(db_config.connection_url)

    stored_hashes = []
    hash_match_found = False
    warning = None
    schema_preview = None
    schema_found = False
    error = None

    try:
        if vector_db.db_type == "chromadb":
            all_items = vector_db.schema_collection.get(include=["metadatas"])
            stored_hashes = list(
                set(m.get("connection_hash") for m in all_items.get("metadatas", []))
            )
        elif vector_db.db_type == "qdrant":
            points, _ = vector_db.client.scroll(
                collection_name="schema_embeddings",
                limit=1000,
                with_payload=True,
                with_vectors=False,
            )
            stored_hashes = list(set(p.payload.get("connection_hash") for p in points))

        hash_match_found = conn_hash in stored_hashes

        if not hash_match_found and stored_hashes:
            warning = (
                f"Connection hash '{conn_hash}' not found in stored schemas. "
                f"Available hashes: {stored_hashes}. "
                "This usually means the connection URL changed slightly between schema extraction and query."
            )

        schema_text = vector_db.get_relevant_schema(
            db_config.connection_url, "show all tables", max_items=5
        )
        schema_preview = schema_text[:500] if schema_text else None
        schema_found = "No schema information available" not in schema_text

    except Exception as e:
        logger.error("Debug schema lookup error", error=str(e))
        error = str(e)

    return DebugSchemaResponse(
        session_id=session_id,
        db_type=db_config.db_type,
        connection_hash_for_lookup=conn_hash,
        schema_ready_in_session=session.get("schema_ready", False),
        schema_error_in_session=session.get("schema_error"),
        vector_db_type=vector_db.db_type,
        embedding_enabled=vector_db.embedding_fn is not None,
        stored_hashes=stored_hashes,
        hash_match_found=hash_match_found,
        warning=warning,
        schema_preview=schema_preview,
        schema_found=schema_found,
        error=error,
    )


# ============ Parameterized routes (must come AFTER specific routes) ============


@router.get(
    "/schema/{session_id}",
    response_model=SchemaResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_schema(session_id: str) -> SchemaResponse:
    """Get cached schema for session"""
    # Session lookup only (no CSRF for GET)
    session = get_session(session_id)

    db_config = DatabaseConfig(**session["db_config"])

    # Try to get from vector DB
    schema_text = vector_db.get_full_schema_text(db_config.connection_url)

    if schema_text == "No schema available":
        # Extract fresh
        schema = await DatabaseService.extract_schema(db_config)
        vector_db.store_schema(db_config.connection_url, schema)
        return SchemaResponse(
            db_type=schema.get("db_type"),
            tables=schema.get("tables"),
            views=schema.get("views"),
            collections=schema.get("collections"),
            extracted_at=schema.get("extracted_at"),
        )

    return SchemaResponse(schema_text=schema_text)
