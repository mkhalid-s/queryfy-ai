"""
QueryfyAI - Data Dictionary API

REST API endpoints for managing data dictionary:
- Business Terms (CRUD + semantic search)
- Query Patterns (CRUD + few-shot examples)
- Column Descriptions (CRUD + schema enrichment)
- Bulk Import/Export
- Enhanced Schema with merged descriptions
"""

import csv
import io
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, model_validator

from app.core.csrf_utils import verify_csrf_token
from app.core.dependencies import get_session
from app.core.logging_config import get_logger
from app.models.schemas import ERROR_RESPONSES, DatabaseConfig
from app.services.data_dictionary import data_dictionary
from app.services.database_service import DatabaseService
from app.services.vector_db import vector_db

router = APIRouter()
logger = get_logger(__name__)


# ============ Pydantic Models for Data Dictionary ============


class BusinessTermCreate(BaseModel):
    """Request to create/update a business term"""

    term: str = Field(..., min_length=1, max_length=255)
    definition: str = Field(..., min_length=1)
    sql_expression: str = Field(..., min_length=1)
    scope_type: str = Field(
        default="database", pattern="^(global|database|tenant|session)$"
    )
    scope_key: Optional[str] = None
    synonyms: Optional[List[str]] = None
    examples: Optional[List[str]] = None
    category: Optional[str] = None

    @model_validator(mode="after")
    def validate_scope_key(self):
        if self.scope_type in ("tenant", "session") and not self.scope_key:
            raise ValueError(
                "scope_key is required when scope_type is 'tenant' or 'session'"
            )
        return self


class BusinessTermUpdate(BaseModel):
    """Request to update a business term"""

    term: Optional[str] = Field(None, min_length=1, max_length=255)
    definition: Optional[str] = None
    sql_expression: Optional[str] = None
    synonyms: Optional[List[str]] = None
    examples: Optional[List[str]] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


class BusinessTermResponse(BaseModel):
    """Business term response"""

    id: str
    connection_hash: str
    term: str
    definition: str
    sql_expression: str
    scope_type: str
    scope_key: Optional[str] = None
    synonyms: List[str] = []
    examples: List[str] = []
    category: Optional[str] = None
    usage_count: int = 0
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BusinessTermListResponse(BaseModel):
    """Paginated list of business terms"""

    items: List[BusinessTermResponse]
    total: int
    limit: int
    offset: int


class QueryPatternCreate(BaseModel):
    """Request to create a query pattern"""

    natural_query: str = Field(..., min_length=3)
    sql: str = Field(..., min_length=1)
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    complexity: Optional[str] = Field(None, pattern="^(simple|medium|complex)$")
    is_curated: bool = False


class QueryPatternUpdate(BaseModel):
    """Request to update a query pattern"""

    natural_query: Optional[str] = Field(None, min_length=3)
    sql: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    complexity: Optional[str] = Field(None, pattern="^(simple|medium|complex)$")
    is_curated: Optional[bool] = None
    rating: Optional[int] = Field(None, ge=-1, le=5)
    is_active: Optional[bool] = None


class QueryPatternResponse(BaseModel):
    """Query pattern response"""

    id: str
    connection_hash: str
    natural_query: str
    sql: str
    description: Optional[str] = None
    tags: List[str] = []
    complexity: Optional[str] = None
    is_curated: bool = False
    rating: int = 0
    execution_time_ms: Optional[int] = None
    result_count: Optional[int] = None
    success_count: int = 1
    fail_count: int = 0
    is_active: bool = True
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class QueryPatternListResponse(BaseModel):
    """Paginated list of query patterns"""

    items: List[QueryPatternResponse]
    total: int
    limit: int
    offset: int


class ColumnDescriptionCreate(BaseModel):
    """Request to create/update a column description"""

    table_name: str = Field(..., min_length=1, max_length=255)
    column_name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    schema_name: Optional[str] = None
    business_name: Optional[str] = None
    data_type_hint: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    sample_values: Optional[List[str]] = None
    value_pattern: Optional[str] = None
    is_pii: bool = False
    is_sensitive: bool = False


class ColumnDescriptionUpdate(BaseModel):
    """Request to update a column description"""

    description: Optional[str] = None
    business_name: Optional[str] = None
    data_type_hint: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    sample_values: Optional[List[str]] = None
    value_pattern: Optional[str] = None
    is_pii: Optional[bool] = None
    is_sensitive: Optional[bool] = None
    is_active: Optional[bool] = None


class ColumnDescriptionResponse(BaseModel):
    """Column description response"""

    id: str
    connection_hash: str
    schema_name: Optional[str] = None
    table_name: str
    column_name: str
    description: str
    business_name: Optional[str] = None
    data_type_hint: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    sample_values: Optional[List[str]] = None
    is_pii: bool = False
    is_sensitive: bool = False
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ColumnDescriptionListResponse(BaseModel):
    """Paginated list of column descriptions"""

    items: List[ColumnDescriptionResponse]
    total: int
    limit: int
    offset: int


class BulkImportResponse(BaseModel):
    """Response from bulk import operation"""

    total: int
    created: int
    updated: int
    failed: int
    errors: List[dict] = []
    import_id: Optional[int] = None


class ImportHistoryItem(BaseModel):
    """Import history item"""

    id: int
    import_type: str
    file_name: Optional[str] = None
    file_format: Optional[str] = None
    records_total: int
    records_created: int
    records_updated: int
    records_failed: int
    imported_at: Optional[str] = None


class DataDictionaryStatsResponse(BaseModel):
    """Data dictionary statistics"""

    total_terms: int
    total_patterns: int
    total_columns: int
    curated_patterns: int


class EnhancedColumnInfo(BaseModel):
    """Column info enriched with description"""

    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: Optional[str] = None
    # From data dictionary
    description: Optional[str] = None
    business_name: Optional[str] = None
    data_type_hint: Optional[str] = None
    sample_values: Optional[List[str]] = None
    is_pii: bool = False
    is_sensitive: bool = False


class EnhancedTableInfo(BaseModel):
    """Table info enriched with column descriptions"""

    name: str
    schema_name: Optional[str] = None
    columns: List[EnhancedColumnInfo]
    row_count: Optional[int] = None


class EnhancedSchemaResponse(BaseModel):
    """Schema with merged data dictionary descriptions"""

    db_type: str
    tables: List[EnhancedTableInfo]
    connection_hash: str


# ============ Helper Functions ============


def get_connection_hash(session_id: str) -> str:
    """Get connection hash from session"""
    session = get_session(session_id)
    db_config = DatabaseConfig(**session["db_config"])
    return vector_db._hash_connection(db_config.connection_url)


# ============ Business Terms Endpoints ============


@router.post(
    "/terms", response_model=BusinessTermResponse, responses={404: ERROR_RESPONSES[404]}
)
async def create_business_term(
    session_id: str,
    term: BusinessTermCreate,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> BusinessTermResponse:
    """Create or update a business term"""
    connection_hash = get_connection_hash(session_id)

    result = await data_dictionary.add_business_term(
        connection_hash=connection_hash,
        term=term.term,
        definition=term.definition,
        sql_expression=term.sql_expression,
        scope_type=term.scope_type,
        scope_key=term.scope_key,
        synonyms=term.synonyms,
        examples=term.examples,
        category=term.category,
    )

    return BusinessTermResponse(**result)


@router.get(
    "/terms",
    response_model=BusinessTermListResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def list_business_terms(
    session_id: str,
    scope_type: Optional[str] = None,
    category: Optional[str] = None,
    include_global: bool = True,
    search: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> BusinessTermListResponse:
    """List business terms with filtering and pagination"""
    connection_hash = get_connection_hash(session_id)

    result = await data_dictionary.list_business_terms(
        connection_hash=connection_hash,
        scope_type=scope_type,
        category=category,
        include_global=include_global,
        search=search,
        limit=limit,
        offset=offset,
    )

    return BusinessTermListResponse(**result)


@router.get(
    "/terms/{term_id}",
    response_model=BusinessTermResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_business_term(term_id: str, session_id: str = Query(...)) -> BusinessTermResponse:
    """Get a business term by ID"""
    connection_hash = get_connection_hash(session_id)
    result = await data_dictionary.get_business_term(term_id)
    if not result or result.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Business term not found")
    return BusinessTermResponse(**result)


@router.put(
    "/terms/{term_id}",
    response_model=BusinessTermResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def update_business_term(
    term_id: str,
    update: BusinessTermUpdate,
    session_id: str = Query(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> BusinessTermResponse:
    """Update a business term"""
    connection_hash = get_connection_hash(session_id)
    existing = await data_dictionary.get_business_term(term_id)
    if not existing or existing.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Business term not found")
    updates = update.model_dump(exclude_unset=True)
    result = await data_dictionary.update_business_term(term_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Business term not found")
    return BusinessTermResponse(**result)


@router.delete("/terms/{term_id}", responses={404: ERROR_RESPONSES[404]})
async def delete_business_term(
    term_id: str,
    hard_delete: bool = False,
    session_id: str = Query(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> dict:
    """Delete a business term (soft delete by default)"""
    connection_hash = get_connection_hash(session_id)
    existing = await data_dictionary.get_business_term(term_id)
    if not existing or existing.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Business term not found")
    success = await data_dictionary.delete_business_term(
        term_id, hard_delete=hard_delete
    )
    if not success:
        raise HTTPException(status_code=404, detail="Business term not found")
    return {"message": "Business term deleted successfully"}


@router.get(
    "/terms/search/relevant",
    response_model=List[BusinessTermResponse],
    responses={404: ERROR_RESPONSES[404]},
)
async def search_relevant_terms(
    session_id: str, query: str, limit: int = Query(default=5, ge=1, le=20)
) -> List[BusinessTermResponse]:
    """Find business terms relevant to a natural language query"""
    connection_hash = get_connection_hash(session_id)

    results = await data_dictionary.get_relevant_terms(
        query=query, connection_hash=connection_hash, limit=limit
    )

    return [BusinessTermResponse(**r) for r in results]


# ============ Query Patterns Endpoints ============


@router.post(
    "/patterns",
    response_model=QueryPatternResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def create_query_pattern(
    session_id: str,
    pattern: QueryPatternCreate,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> QueryPatternResponse:
    """Create a query pattern for few-shot learning"""
    connection_hash = get_connection_hash(session_id)

    result = await data_dictionary.add_query_pattern(
        connection_hash=connection_hash,
        natural_query=pattern.natural_query,
        sql=pattern.sql,
        description=pattern.description,
        tags=pattern.tags,
        complexity=pattern.complexity,
        is_curated=pattern.is_curated,
    )

    return QueryPatternResponse(**result)


@router.get(
    "/patterns",
    response_model=QueryPatternListResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def list_query_patterns(
    session_id: str,
    is_curated: Optional[bool] = None,
    complexity: Optional[str] = None,
    min_rating: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> QueryPatternListResponse:
    """List query patterns with filtering and pagination"""
    connection_hash = get_connection_hash(session_id)

    result = await data_dictionary.list_query_patterns(
        connection_hash=connection_hash,
        is_curated=is_curated,
        complexity=complexity,
        min_rating=min_rating,
        search=search,
        limit=limit,
        offset=offset,
    )

    return QueryPatternListResponse(**result)


@router.get(
    "/patterns/{pattern_id}",
    response_model=QueryPatternResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_query_pattern(pattern_id: str, session_id: str = Query(...)) -> QueryPatternResponse:
    """Get a query pattern by ID"""
    connection_hash = get_connection_hash(session_id)
    result = await data_dictionary.get_query_pattern(pattern_id)
    if not result or result.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Query pattern not found")
    return QueryPatternResponse(**result)


@router.put(
    "/patterns/{pattern_id}",
    response_model=QueryPatternResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def update_query_pattern(
    pattern_id: str,
    update: QueryPatternUpdate,
    session_id: str = Query(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> QueryPatternResponse:
    """Update a query pattern"""
    connection_hash = get_connection_hash(session_id)
    existing = await data_dictionary.get_query_pattern(pattern_id)
    if not existing or existing.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Query pattern not found")
    updates = update.model_dump(exclude_unset=True)
    result = await data_dictionary.update_query_pattern(pattern_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Query pattern not found")
    return QueryPatternResponse(**result)


@router.delete("/patterns/{pattern_id}", responses={404: ERROR_RESPONSES[404]})
async def delete_query_pattern(
    pattern_id: str,
    hard_delete: bool = False,
    session_id: str = Query(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> dict:
    """Delete a query pattern"""
    connection_hash = get_connection_hash(session_id)
    existing = await data_dictionary.get_query_pattern(pattern_id)
    if not existing or existing.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Query pattern not found")
    success = await data_dictionary.delete_query_pattern(
        pattern_id, hard_delete=hard_delete
    )
    if not success:
        raise HTTPException(status_code=404, detail="Query pattern not found")
    return {"message": "Query pattern deleted successfully"}


@router.post("/patterns/{pattern_id}/rate", responses={404: ERROR_RESPONSES[404]})
async def rate_query_pattern(
    pattern_id: str,
    rating: int = Query(..., ge=-1, le=5),
    session_id: str = Query(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> dict:
    """Rate a query pattern (thumbs up/down)"""
    connection_hash = get_connection_hash(session_id)
    existing = await data_dictionary.get_query_pattern(pattern_id)
    if not existing or existing.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Query pattern not found")
    await data_dictionary.rate_query_pattern(pattern_id, rating)
    return {"message": "Rating recorded"}


@router.get("/patterns/search/similar", responses={404: ERROR_RESPONSES[404]})
async def search_similar_patterns(
    session_id: str, query: str, limit: int = Query(default=3, ge=1, le=10)
) -> List[dict]:
    """Find similar query patterns for few-shot learning"""
    connection_hash = get_connection_hash(session_id)

    results = await data_dictionary.get_similar_queries(
        query=query, connection_hash=connection_hash, limit=limit
    )

    return results


# ============ Column Descriptions Endpoints ============


@router.post(
    "/columns",
    response_model=ColumnDescriptionResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def create_column_description(
    session_id: str,
    column: ColumnDescriptionCreate,
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> ColumnDescriptionResponse:
    """Create or update a column description"""
    connection_hash = get_connection_hash(session_id)

    result = await data_dictionary.add_column_description(
        connection_hash=connection_hash,
        table_name=column.table_name,
        column_name=column.column_name,
        description=column.description,
        schema_name=column.schema_name,
        business_name=column.business_name,
        data_type_hint=column.data_type_hint,
        allowed_values=column.allowed_values,
        sample_values=column.sample_values,
        value_pattern=column.value_pattern,
        is_pii=column.is_pii,
        is_sensitive=column.is_sensitive,
    )

    return ColumnDescriptionResponse(**result)


@router.get(
    "/columns",
    response_model=ColumnDescriptionListResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def list_column_descriptions(
    session_id: str,
    table_name: Optional[str] = None,
    schema_name: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ColumnDescriptionListResponse:
    """List column descriptions with filtering and pagination"""
    connection_hash = get_connection_hash(session_id)

    result = await data_dictionary.list_column_descriptions(
        connection_hash=connection_hash,
        table_name=table_name,
        schema_name=schema_name,
        search=search,
        limit=limit,
        offset=offset,
    )

    return ColumnDescriptionListResponse(**result)


@router.get(
    "/columns/{column_id}",
    response_model=ColumnDescriptionResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_column_description(column_id: str, session_id: str = Query(...)) -> ColumnDescriptionResponse:
    """Get a column description by ID"""
    connection_hash = get_connection_hash(session_id)
    result = await data_dictionary.get_column_description(column_id)
    if not result or result.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Column description not found")
    return ColumnDescriptionResponse(**result)


@router.put(
    "/columns/{column_id}",
    response_model=ColumnDescriptionResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def update_column_description(
    column_id: str,
    update: ColumnDescriptionUpdate,
    session_id: str = Query(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> ColumnDescriptionResponse:
    """Update a column description"""
    connection_hash = get_connection_hash(session_id)
    existing = await data_dictionary.get_column_description(column_id)
    if not existing or existing.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Column description not found")
    updates = update.model_dump(exclude_unset=True)
    result = await data_dictionary.update_column_description(column_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Column description not found")
    return ColumnDescriptionResponse(**result)


@router.delete("/columns/{column_id}", responses={404: ERROR_RESPONSES[404]})
async def delete_column_description(
    column_id: str,
    hard_delete: bool = False,
    session_id: str = Query(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> dict:
    """Delete a column description"""
    connection_hash = get_connection_hash(session_id)
    existing = await data_dictionary.get_column_description(column_id)
    if not existing or existing.get("connection_hash") != connection_hash:
        raise HTTPException(status_code=404, detail="Column description not found")
    success = await data_dictionary.delete_column_description(
        column_id, hard_delete=hard_delete
    )
    if not success:
        raise HTTPException(status_code=404, detail="Column description not found")
    return {"message": "Column description deleted successfully"}


# ============ Enhanced Schema Endpoint ============


@router.get(
    "/schema/enhanced/{session_id}",
    response_model=EnhancedSchemaResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_enhanced_schema(session_id: str) -> EnhancedSchemaResponse:
    """
    Get database schema with merged data dictionary descriptions.
    Combines extracted schema with user-provided column descriptions.
    Supports both SQL databases (tables) and NoSQL databases (collections).
    """
    session = get_session(session_id)
    db_config = DatabaseConfig(**session["db_config"])
    connection_hash = vector_db._hash_connection(db_config.connection_url)

    # Get base schema
    schema = await DatabaseService.extract_schema(db_config)

    # Get all column descriptions for this connection
    col_result = await data_dictionary.list_column_descriptions(
        connection_hash=connection_hash, limit=5000
    )
    col_descriptions = {item["id"]: item for item in col_result["items"]}

    # Determine source: use 'tables' for SQL, 'collections' for NoSQL (MongoDB, etc.)
    # Also support DynamoDB which uses 'tables' but has different structure
    source_items = schema.get("tables", [])

    # For NoSQL databases, check collections if tables is empty
    if not source_items and schema.get("collections"):
        source_items = schema.get("collections", [])

    # Build enhanced tables/collections
    enhanced_tables = []
    for item in source_items:
        item_name = item.get("name", "")
        schema_name = item.get("schema")

        # Get columns/fields - NoSQL uses 'fields', SQL uses 'columns'
        source_columns = item.get("columns", []) or item.get("fields", [])

        enhanced_columns = []
        for col in source_columns:
            col_name = col.get("name", "")

            # Look up description
            from app.models.db_models import ColumnDescription

            col_id = ColumnDescription.generate_id(
                connection_hash, schema_name, item_name, col_name
            )
            desc_data = col_descriptions.get(col_id, {})

            enhanced_col = EnhancedColumnInfo(
                name=col_name,
                type=col.get("type", "unknown"),
                nullable=col.get("nullable", True),
                primary_key=col.get("primary_key", False),
                foreign_key=col.get("foreign_key"),
                description=desc_data.get("description"),
                business_name=desc_data.get("business_name"),
                data_type_hint=desc_data.get("data_type_hint"),
                sample_values=desc_data.get("sample_values"),
                is_pii=desc_data.get("is_pii", False),
                is_sensitive=desc_data.get("is_sensitive", False),
            )
            enhanced_columns.append(enhanced_col)

        enhanced_table = EnhancedTableInfo(
            name=item_name,
            schema_name=schema_name,
            columns=enhanced_columns,
            row_count=item.get("row_count") or item.get("estimated_count"),
        )
        enhanced_tables.append(enhanced_table)

    return EnhancedSchemaResponse(
        db_type=db_config.db_type,
        tables=enhanced_tables,
        connection_hash=connection_hash,
    )


# ============ Bulk Import Endpoints ============


@router.post(
    "/import/terms",
    response_model=BulkImportResponse,
    responses={400: ERROR_RESPONSES[400], 404: ERROR_RESPONSES[404]},
)
async def import_business_terms(
    session_id: str,
    file: UploadFile = File(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> BulkImportResponse:
    """
    Bulk import business terms from CSV or JSON file.

    CSV columns: term, definition, sql_expression, synonyms (comma-separated), examples (comma-separated), category
    JSON: array of term objects
    """
    connection_hash = get_connection_hash(session_id)

    # Read file content
    content = await file.read()
    file_format = None
    terms = []

    try:
        # Determine format and parse
        if file.filename and file.filename.endswith(".json"):
            file_format = "json"
            terms = json.loads(content.decode("utf-8"))
        else:
            # Assume CSV
            file_format = "csv"
            reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
            for row in reader:
                term = {
                    "term": row.get("term", "").strip(),
                    "definition": row.get("definition", "").strip(),
                    "sql_expression": row.get("sql_expression", "").strip(),
                    "category": row.get("category", "").strip() or None,
                }

                # Parse comma-separated lists
                if row.get("synonyms"):
                    term["synonyms"] = [
                        s.strip() for s in row["synonyms"].split(",") if s.strip()
                    ]
                if row.get("examples"):
                    term["examples"] = [
                        e.strip() for e in row["examples"].split(",") if e.strip()
                    ]

                terms.append(term)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    # Import terms
    result = await data_dictionary.bulk_import_terms(
        connection_hash=connection_hash,
        terms=terms,
        file_name=file.filename,
        file_format=file_format,
    )

    return BulkImportResponse(**result)


@router.post(
    "/import/columns",
    response_model=BulkImportResponse,
    responses={400: ERROR_RESPONSES[400], 404: ERROR_RESPONSES[404]},
)
async def import_column_descriptions(
    session_id: str,
    file: UploadFile = File(...),
    csrf_token: Optional[str] = Depends(verify_csrf_token),
) -> BulkImportResponse:
    """
    Bulk import column descriptions from CSV or JSON file.

    CSV columns: table_name, column_name, description, schema_name, business_name, data_type_hint, is_pii, is_sensitive
    JSON: array of column description objects
    """
    connection_hash = get_connection_hash(session_id)

    content = await file.read()
    file_format = None
    descriptions = []

    try:
        if file.filename and file.filename.endswith(".json"):
            file_format = "json"
            descriptions = json.loads(content.decode("utf-8"))
        else:
            file_format = "csv"
            reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
            for row in reader:
                desc = {
                    "table_name": row.get("table_name", "").strip(),
                    "column_name": row.get("column_name", "").strip(),
                    "description": row.get("description", "").strip(),
                    "schema_name": row.get("schema_name", "").strip() or None,
                    "business_name": row.get("business_name", "").strip() or None,
                    "data_type_hint": row.get("data_type_hint", "").strip() or None,
                    "is_pii": row.get("is_pii", "").lower() in ("true", "1", "yes"),
                    "is_sensitive": row.get("is_sensitive", "").lower()
                    in ("true", "1", "yes"),
                }

                # Parse allowed/sample values
                if row.get("allowed_values"):
                    desc["allowed_values"] = [
                        v.strip() for v in row["allowed_values"].split(",") if v.strip()
                    ]
                if row.get("sample_values"):
                    desc["sample_values"] = [
                        v.strip() for v in row["sample_values"].split(",") if v.strip()
                    ]

                descriptions.append(desc)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    result = await data_dictionary.bulk_import_column_descriptions(
        connection_hash=connection_hash,
        descriptions=descriptions,
        file_name=file.filename,
        file_format=file_format,
    )

    return BulkImportResponse(**result)


@router.get(
    "/import/history",
    response_model=List[ImportHistoryItem],
    responses={404: ERROR_RESPONSES[404]},
)
async def get_import_history(
    session_id: str, limit: int = Query(default=20, ge=1, le=100)
) -> List[ImportHistoryItem]:
    """Get import history for the current database connection"""
    connection_hash = get_connection_hash(session_id)

    history = await data_dictionary.get_import_history(
        connection_hash=connection_hash, limit=limit
    )

    return [ImportHistoryItem(**h) for h in history]


# ============ Statistics Endpoint ============


@router.get(
    "/stats",
    response_model=DataDictionaryStatsResponse,
    responses={404: ERROR_RESPONSES[404]},
)
async def get_data_dictionary_stats(session_id: str) -> DataDictionaryStatsResponse:
    """Get data dictionary statistics for the current database"""
    connection_hash = get_connection_hash(session_id)

    stats = await data_dictionary.get_stats(connection_hash=connection_hash)

    return DataDictionaryStatsResponse(**stats)


# ============ Export Endpoints ============


@router.get("/export/terms", responses={404: ERROR_RESPONSES[404]})
async def export_business_terms(
    session_id: str, format: str = Query(default="json", pattern="^(json|csv)$")
) -> dict:
    """Export all business terms as JSON or CSV"""
    connection_hash = get_connection_hash(session_id)

    result = await data_dictionary.list_business_terms(
        connection_hash=connection_hash, include_global=False, limit=10000
    )

    if format == "csv":
        output = io.StringIO()
        if result["items"]:
            writer = csv.DictWriter(
                output,
                fieldnames=[
                    "term",
                    "definition",
                    "sql_expression",
                    "synonyms",
                    "examples",
                    "category",
                    "scope_type",
                ],
            )
            writer.writeheader()
            for item in result["items"]:
                writer.writerow(
                    {
                        "term": item["term"],
                        "definition": item["definition"],
                        "sql_expression": item["sql_expression"],
                        "synonyms": ",".join(item.get("synonyms", [])),
                        "examples": ",".join(item.get("examples", [])),
                        "category": item.get("category", ""),
                        "scope_type": item["scope_type"],
                    }
                )

        return {
            "format": "csv",
            "content": output.getvalue(),
            "filename": "business_terms.csv",
        }

    return {
        "format": "json",
        "content": result["items"],
        "filename": "business_terms.json",
    }


@router.get("/export/columns", responses={404: ERROR_RESPONSES[404]})
async def export_column_descriptions(
    session_id: str, format: str = Query(default="json", pattern="^(json|csv)$")
) -> dict:
    """Export all column descriptions as JSON or CSV"""
    connection_hash = get_connection_hash(session_id)

    result = await data_dictionary.list_column_descriptions(
        connection_hash=connection_hash, limit=10000
    )

    if format == "csv":
        output = io.StringIO()
        if result["items"]:
            writer = csv.DictWriter(
                output,
                fieldnames=[
                    "table_name",
                    "column_name",
                    "description",
                    "schema_name",
                    "business_name",
                    "data_type_hint",
                    "allowed_values",
                    "sample_values",
                    "is_pii",
                    "is_sensitive",
                ],
            )
            writer.writeheader()
            for item in result["items"]:
                writer.writerow(
                    {
                        "table_name": item["table_name"],
                        "column_name": item["column_name"],
                        "description": item["description"],
                        "schema_name": item.get("schema_name", ""),
                        "business_name": item.get("business_name", ""),
                        "data_type_hint": item.get("data_type_hint", ""),
                        "allowed_values": ",".join(item.get("allowed_values", [])),
                        "sample_values": ",".join(item.get("sample_values", [])),
                        "is_pii": str(item.get("is_pii", False)),
                        "is_sensitive": str(item.get("is_sensitive", False)),
                    }
                )

        return {
            "format": "csv",
            "content": output.getvalue(),
            "filename": "column_descriptions.csv",
        }

    return {
        "format": "json",
        "content": result["items"],
        "filename": "column_descriptions.json",
    }
