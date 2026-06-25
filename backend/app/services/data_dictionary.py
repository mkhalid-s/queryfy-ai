"""
QueryfyAI - Data Dictionary Service

Persistent storage for business context to improve SQL generation:
- Business term definitions ("revenue" = gross_sales - refunds)
- Column descriptions and semantic meaning
- Successful query patterns for few-shot learning
- Bulk import/export support

HIERARCHICAL ISOLATION:
┌─────────────────────────────────────────────────────────────┐
│  GLOBAL TERMS (scope_type=global)                           │
│  Shared SQL patterns: "last 7 days", "YTD", "MTD"          │
├─────────────────────────────────────────────────────────────┤
│  DATABASE-LEVEL TERMS (scope_type=database)                 │
│  Schema-specific: "revenue" = sales.amount - refunds.amount│
├─────────────────────────────────────────────────────────────┤
│  TENANT-LEVEL TERMS (scope_type=tenant)                     │
│  Company-specific: "VIP" = customers WHERE revenue > 1M    │
├─────────────────────────────────────────────────────────────┤
│  SESSION-LEVEL OVERRIDES (scope_type=session)               │
│  Temporary preferences, user-defined aliases               │
└─────────────────────────────────────────────────────────────┘

Resolution order: session → tenant → database → global
"""

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models.db_models import (
    BusinessTerm,
    ColumnDescription,
    ImportHistory,
    QueryPattern,
)

logger = logging.getLogger(__name__)


def _emit_retrieval_fallback(reason: str) -> None:
    """Best-effort Prometheus emit for retrieval fallback paths.
    Imported lazily so the data_dictionary module doesn't hard-depend
    on prometheus_client (matches the pattern in other services).
    """
    try:
        from app.api.metrics import retrieval_fallback_total

        retrieval_fallback_total.labels(reason=reason).inc()
    except (ImportError, AttributeError):
        # prometheus_client unavailable in smoke environment, or the
        # metric attribute wasn't created (older builds). Best-effort.
        pass


# Prompt injection patterns for validating dictionary content at write time.
# These match the patterns in PromptInjectionValidator and SQLGenerationService.
_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        # Instruction overrides
        r"ignore\s+(all\s+)?previous\s+instructions?",
        r"ignore\s+(all\s+)?above\s+instructions?",
        r"forget\s+(all\s+)?previous\s+instructions?",
        r"disregard\s+(all\s+)?previous\s+instructions?",
        r"override\s+(all\s+)?previous\s+instructions?",
        # Role manipulation
        r"you\s+are\s+now\s+a?",
        r"act\s+as\s+(?:if|a)",
        r"pretend\s+(?:to\s+be|you\s+are)",
        r"roleplay\s+as",
        r"simulate\s+(?:being\s+)?a?",
        # System prompt access
        r"what\s+(?:is|are)\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
        r"show\s+(?:me\s+)?your\s+(?:system\s+)?(?:instructions?|prompt)",
        r"reveal\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
        r"print\s+your\s+(?:system\s+)?(?:instructions?|prompt)",
        # Delimiter injection
        r"```\s*(?:system|user|assistant)",
        r"\[\[(?:system|user|assistant)\]\]",
        r"<\s*(?:system|user|assistant)\s*>",
        # Jailbreak patterns
        r"jailbreak",
        r"dan\s+mode",
        r"developer\s+mode",
        r"bypass\s+(?:filters?|safety|restrictions?)",
    ]
]


def _check_prompt_injection(text: str, field_name: str) -> None:
    """
    Validate that a text field does not contain prompt injection patterns.

    Args:
        text: The content to validate.
        field_name: Name of the field (for error messages).

    Raises:
        ValueError: If suspicious content is detected.
    """
    if not text:
        return
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            logger.warning(
                f"Prompt injection detected in dictionary {field_name}: "
                f"'{match.group(0)}'"
            )
            raise ValueError(
                f"The '{field_name}' field contains content that resembles a "
                f"prompt injection attempt and cannot be saved. "
                f"Please remove the suspicious phrase and try again."
            )


# Scope constants
SCOPE_GLOBAL = "global"
SCOPE_DATABASE = "database"
SCOPE_TENANT = "tenant"
SCOPE_SESSION = "session"


class DataDictionaryService:
    """
    Dual storage:
    - PostgreSQL for structured CRUD operations
    - Vector DB (ChromaDB or Qdrant) for semantic search (optional, lazy-loaded)
    """

    # Vector DB collection names
    COLLECTION_BUSINESS_TERMS = "dd_business_terms"
    COLLECTION_QUERY_PATTERNS = "dd_query_patterns"
    COLLECTION_COLUMN_DESC = "dd_column_descriptions"

    def __init__(self):
        self._vector_db = None
        self._collections = {}
        self._global_terms_initialized = False
        self._qdrant_collections_initialized = set()

    def _get_vector_db(self):
        """Lazy load vector_db to avoid circular imports"""
        if self._vector_db is None:
            try:
                from app.services.vector_db import vector_db

                self._vector_db = vector_db
            except Exception as e:
                logger.warning(f"Vector DB not available: {e}")
        return self._vector_db

    def _get_collection(self, name: str):
        """Get or create a vector DB collection (ChromaDB or Qdrant)"""
        if name not in self._collections:
            vdb = self._get_vector_db()
            if not vdb:
                return None

            if vdb.db_type == "chromadb":
                collection_kwargs = {"metadata": {"hnsw:space": "cosine"}}
                if vdb.embedding_fn:
                    collection_kwargs["embedding_function"] = vdb.embedding_fn
                self._collections[name] = vdb.client.get_or_create_collection(
                    name=name, **collection_kwargs
                )
            elif vdb.db_type == "qdrant":
                # Ensure Qdrant collection exists
                self._ensure_qdrant_collection(name)
                self._collections[name] = name
            else:
                return None

        return self._collections.get(name)

    def _ensure_qdrant_collection(self, name: str):
        """Ensure a Qdrant collection exists with proper vector config"""
        if name in self._qdrant_collections_initialized:
            return

        vdb = self._get_vector_db()
        if not vdb or vdb.db_type != "qdrant":
            return

        try:
            from qdrant_client.models import Distance, VectorParams

            from app.core.config import settings

            # Check if collection exists
            collections = [c.name for c in vdb.client.get_collections().collections]
            if name not in collections:
                # Determine vector size based on embedding provider
                vector_size = 384  # Default for all-MiniLM-L6-v2
                if settings.EMBEDDING_PROVIDER == "openai":
                    vector_size = 1536  # OpenAI ada-002

                vdb.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=vector_size, distance=Distance.COSINE
                    ),
                )
                logger.info(f"Created Qdrant collection: {name}")

            self._qdrant_collections_initialized.add(name)

        except Exception as e:
            logger.warning(f"Failed to create Qdrant collection {name}: {e}")

    def _get_scope_key(
        self,
        scope: str,
        connection_hash: Optional[str] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        """Generate hierarchical scope key"""
        if scope == SCOPE_GLOBAL:
            return None  # Global scope has no scope_key
        elif scope == SCOPE_DATABASE:
            return None  # Database scope uses connection_hash directly
        elif scope == SCOPE_TENANT:
            return tenant_id
        elif scope == SCOPE_SESSION:
            return session_id
        return None

    # ============ Global Terms Initialization ============

    async def ensure_global_terms(self, session: AsyncSession):
        """Initialize common global terms if they don't exist"""
        if self._global_terms_initialized:
            return

        global_terms = [
            {
                "term": "last 7 days",
                "definition": "Records from the past 7 days",
                "sql_expression": "created_at >= CURRENT_DATE - INTERVAL '7 days'",
                "examples": ["Show sales from last 7 days"],
                "category": "time",
            },
            {
                "term": "last 30 days",
                "definition": "Records from the past 30 days",
                "sql_expression": "created_at >= CURRENT_DATE - INTERVAL '30 days'",
                "examples": ["Orders in last 30 days"],
                "category": "time",
            },
            {
                "term": "YTD",
                "definition": "Year to date - from January 1st of current year",
                "sql_expression": "created_at >= DATE_TRUNC('year', CURRENT_DATE)",
                "examples": ["YTD revenue", "Sales YTD"],
                "category": "time",
            },
            {
                "term": "MTD",
                "definition": "Month to date - from 1st of current month",
                "sql_expression": "created_at >= DATE_TRUNC('month', CURRENT_DATE)",
                "examples": ["MTD orders", "Revenue MTD"],
                "category": "time",
            },
            {
                "term": "top 10",
                "definition": "Limit results to top 10",
                "sql_expression": "LIMIT 10",
                "examples": ["Top 10 customers", "Show top 10"],
                "category": "limit",
            },
            {
                "term": "active",
                "definition": "Active/enabled records",
                "sql_expression": "status = 'active' OR is_active = true",
                "examples": ["Active users", "Show active customers"],
                "category": "status",
            },
        ]

        # Use special connection_hash for global terms
        global_hash = "0000000000000000"

        for term_data in global_terms:
            term_str = str(term_data['term'])  # Ensure it's a string for encoding
            term_id = (
                f"global_{hashlib.md5(term_str.encode()).hexdigest()[:8]}"
            )

            # Check if term exists
            result = await session.execute(
                select(BusinessTerm).where(BusinessTerm.id == term_id)
            )
            if result.scalar_one_or_none() is None:
                term = BusinessTerm(
                    id=term_id,
                    connection_hash=global_hash,
                    term=str(term_data["term"]),
                    definition=str(term_data["definition"]),
                    sql_expression=str(term_data["sql_expression"]),
                    scope_type=SCOPE_GLOBAL,
                    scope_key=None,
                    examples=term_data.get("examples", []),
                    synonyms=[],
                    category=str(term_data["category"]) if term_data.get("category") else None,
                    is_active=True,
                )
                session.add(term)

        await session.flush()
        self._global_terms_initialized = True
        logger.info("Global business terms initialized")

    # ============ Business Terms CRUD ============

    async def add_business_term(
        self,
        connection_hash: str,
        term: str,
        definition: str,
        sql_expression: str,
        scope_type: str = SCOPE_DATABASE,
        scope_key: Optional[str] = None,
        synonyms: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        category: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add or update a business term definition.

        Args:
            connection_hash: Database connection identifier
            term: The business term (e.g., "revenue", "active user")
            definition: Human-readable definition
            sql_expression: SQL equivalent
            scope_type: Isolation level (global, database, tenant, session)
            scope_key: Tenant ID or session ID for narrower scopes
            synonyms: Alternative names for the term
            examples: Example queries using this term
            category: Term category for organization
            created_by: User who created the term

        Returns:
            Created/updated term as dictionary

        Raises:
            ValueError: If definition or sql_expression contains prompt injection patterns.
        """
        # Validate content fields for prompt injection before persisting
        _check_prompt_injection(definition, "definition")
        _check_prompt_injection(sql_expression, "sql_expression")

        async with get_db_session() as session:
            await self.ensure_global_terms(session)

            # Generate deterministic ID based on connection + scope + term
            id_source = (
                f"{connection_hash}_{scope_type}_{scope_key or ''}_{term.lower()}"
            )
            term_id = hashlib.sha256(id_source.encode()).hexdigest()[:64]

            # Check for existing term
            result = await session.execute(
                select(BusinessTerm).where(BusinessTerm.id == term_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing term
                existing.definition = definition
                existing.sql_expression = sql_expression
                existing.synonyms = synonyms or existing.synonyms
                existing.examples = examples or existing.examples
                existing.category = category or existing.category
                existing.updated_at = datetime.utcnow()
                await session.flush()
                term_obj = existing
            else:
                # Create new term
                term_obj = BusinessTerm(
                    id=term_id,
                    connection_hash=connection_hash,
                    term=term,
                    definition=definition,
                    sql_expression=sql_expression,
                    scope_type=scope_type,
                    scope_key=scope_key,
                    synonyms=synonyms or [],
                    examples=examples or [],
                    category=category,
                    created_by=created_by,
                    is_active=True,
                )
                session.add(term_obj)
                await session.flush()

            # Store in ChromaDB for semantic search
            self._index_term_in_vector_db(term_obj)

            logger.info(
                f"Added business term: {term} (connection={connection_hash[:8]})"
            )
            return term_obj.to_dict()

    def _index_term_in_vector_db(self, term: BusinessTerm):
        """Index a term in vector DB (ChromaDB or Qdrant) for semantic search"""
        try:
            collection = self._get_collection(self.COLLECTION_BUSINESS_TERMS)
            if collection is None:
                return

            doc_text = f"Term: {term.term}\nDefinition: {term.definition}\nSQL: {term.sql_expression}"
            metadata = {
                "term": term.term,
                "connection_hash": term.connection_hash,
                "scope_type": term.scope_type,
                "sql_expression": term.sql_expression[:500] if term.sql_expression else None,
            }

            vdb = self._get_vector_db()
            if vdb and vdb.db_type == "chromadb":
                collection.upsert(
                    ids=[term.id], documents=[doc_text], metadatas=[metadata]
                )
            elif vdb and vdb.db_type == "qdrant":
                embeddings = vdb._generate_embeddings([doc_text])
                if embeddings:
                    from qdrant_client.models import PointStruct

                    vdb.client.upsert(
                        collection_name=collection,
                        points=[
                            PointStruct(
                                id=hash(term.id) % (2**63),
                                vector=embeddings[0],
                                payload={
                                    **metadata,
                                    "document": doc_text,
                                    "id": term.id,
                                },
                            )
                        ],
                    )
        except Exception as e:
            logger.warning(f"Failed to index term in vector DB: {e}")

    async def get_business_term(self, term_id: str) -> Optional[Dict[str, Any]]:
        """Get a single business term by ID"""
        async with get_db_session() as session:
            result = await session.execute(
                select(BusinessTerm).where(
                    and_(BusinessTerm.id == term_id, BusinessTerm.is_active == True)  # noqa: E712
                )
            )
            term = result.scalar_one_or_none()
            return term.to_dict() if term else None

    async def update_business_term(
        self, term_id: str, **updates
    ) -> Optional[Dict[str, Any]]:
        """Update a business term.

        Raises:
            ValueError: If updated definition or sql_expression contains prompt injection patterns.
        """
        # Validate content fields if they are being updated
        if "definition" in updates and updates["definition"]:
            _check_prompt_injection(updates["definition"], "definition")
        if "sql_expression" in updates and updates["sql_expression"]:
            _check_prompt_injection(updates["sql_expression"], "sql_expression")

        async with get_db_session() as session:
            result = await session.execute(
                select(BusinessTerm).where(BusinessTerm.id == term_id)
            )
            term = result.scalar_one_or_none()

            if not term:
                return None

            # Apply updates
            allowed_fields = {
                "term",
                "definition",
                "sql_expression",
                "synonyms",
                "examples",
                "category",
                "is_active",
            }
            for field, value in updates.items():
                if field in allowed_fields and hasattr(term, field):
                    setattr(term, field, value)

            term.updated_at = datetime.utcnow()
            await session.flush()

            # Re-index in vector DB
            self._index_term_in_vector_db(term)

            return term.to_dict()

    async def delete_business_term(
        self, term_id: str, hard_delete: bool = False
    ) -> bool:
        """Delete a business term (soft delete by default)"""
        async with get_db_session() as session:
            if hard_delete:
                result = await session.execute(
                    delete(BusinessTerm).where(BusinessTerm.id == term_id)
                )
                await session.commit()
                return result.rowcount > 0  # type: ignore[attr-defined]
            else:
                result = await session.execute(
                    update(BusinessTerm)
                    .where(BusinessTerm.id == term_id)
                    .values(is_active=False, updated_at=datetime.utcnow())
                )
                await session.commit()
                return result.rowcount > 0  # type: ignore[attr-defined]

    async def list_business_terms(
        self,
        connection_hash: str,
        scope_type: Optional[str] = None,
        category: Optional[str] = None,
        include_global: bool = True,
        include_inactive: bool = False,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List business terms with filtering and pagination"""
        async with get_db_session() as session:
            await self.ensure_global_terms(session)

            # Build query
            conditions = []

            # Connection filter (include global terms if requested)
            if include_global:
                conditions.append(
                    or_(
                        BusinessTerm.connection_hash == connection_hash,
                        BusinessTerm.scope_type == SCOPE_GLOBAL,
                    )
                )
            else:
                conditions.append(BusinessTerm.connection_hash == connection_hash)

            # Active filter
            if not include_inactive:
                conditions.append(BusinessTerm.is_active == True)  # noqa: E712

            # Scope filter
            if scope_type:
                conditions.append(BusinessTerm.scope_type == scope_type)

            # Category filter
            if category:
                conditions.append(BusinessTerm.category == category)

            # Search filter
            if search:
                search_pattern = f"%{search}%"
                conditions.append(
                    or_(
                        BusinessTerm.term.ilike(search_pattern),
                        BusinessTerm.definition.ilike(search_pattern),
                    )
                )

            # Count total
            count_query = select(func.count(BusinessTerm.id)).where(and_(*conditions))
            total_result = await session.execute(count_query)
            total = total_result.scalar()

            # Fetch items
            query = (
                select(BusinessTerm)
                .where(and_(*conditions))
                .order_by(BusinessTerm.term)
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(query)
            terms = result.scalars().all()

            return {
                "items": [t.to_dict() for t in terms],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def get_relevant_terms(
        self,
        query: str,
        connection_hash: str,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Find business terms relevant to the query.
        Uses semantic search if available, falls back to text matching.

        Resolution order: session → tenant → database → global
        """
        # Try semantic search first
        try:
            collection = self._get_collection(self.COLLECTION_BUSINESS_TERMS)
            vdb = self._get_vector_db()

            term_ids = []

            if collection and vdb:
                if vdb.db_type == "chromadb":
                    # ChromaDB: Use query_texts
                    conn_filter = {
                        "$or": [
                            {"connection_hash": connection_hash},
                            {"scope_type": SCOPE_GLOBAL},
                        ]
                    }

                    # Run sync ChromaDB call in executor to avoid blocking event loop
                    loop = asyncio.get_event_loop()
                    results = await loop.run_in_executor(
                        None,
                        lambda: collection.query(
                            query_texts=[query], n_results=limit * 2, where=conn_filter
                        )
                    )

                    if results["ids"] and results["ids"][0]:
                        term_ids = results["ids"][0]

                elif vdb.db_type == "qdrant":
                    # Qdrant: Generate embeddings and query
                    embeddings = vdb._generate_embeddings([query])
                    if embeddings:
                        from qdrant_client.models import (
                            FieldCondition,
                            Filter,
                            MatchValue,
                        )

                        # Query for matching connection_hash OR global scope
                        # Note: Qdrant doesn't support OR in filters directly,
                        # so we do two queries and combine results
                        results_conn = vdb.client.query_points(
                            collection_name=collection,
                            query=embeddings[0],
                            query_filter=Filter(
                                must=[
                                    FieldCondition(
                                        key="connection_hash",
                                        match=MatchValue(value=connection_hash),
                                    )
                                ]
                            ),
                            limit=limit * 2,
                        )

                        results_global = vdb.client.query_points(
                            collection_name=collection,
                            query=embeddings[0],
                            query_filter=Filter(
                                must=[
                                    FieldCondition(
                                        key="scope_type",
                                        match=MatchValue(value=SCOPE_GLOBAL),
                                    )
                                ]
                            ),
                            limit=limit,
                        )

                        # Combine results, deduplicate by id
                        seen_ids = set()
                        for point in results_conn.points + results_global.points:
                            point_id = point.payload.get("id")
                            if point_id and point_id not in seen_ids:
                                term_ids.append(point_id)
                                seen_ids.add(point_id)

                if term_ids:
                    # Fetch full term details from database
                    async with get_db_session() as session:
                        result = await session.execute(
                            select(BusinessTerm).where(
                                and_(
                                    BusinessTerm.id.in_(term_ids),
                                    BusinessTerm.is_active == True,  # noqa: E712
                                )
                            )
                        )
                        terms = result.scalars().all()

                        # Sort by scope priority
                        scope_priority = {
                            SCOPE_SESSION: 0,
                            SCOPE_TENANT: 1,
                            SCOPE_DATABASE: 2,
                            SCOPE_GLOBAL: 3,
                        }
                        sorted_terms = sorted(
                            terms, key=lambda t: scope_priority.get(t.scope_type or "", 4)
                        )

                        # Deduplicate by term name (keep highest priority)
                        seen_terms: Dict[str, Dict[str, Any]] = {}
                        for term in sorted_terms:
                            if term.term:
                                term_lower = term.term.lower()
                                if term_lower not in seen_terms:
                                    seen_terms[term_lower] = term.to_dict()

                        return list(seen_terms.values())[:limit]

        except Exception as e:
            logger.warning(f"Semantic term search failed: {e}")

        # Fallback: database text search
        async with get_db_session() as session:
            await self.ensure_global_terms(session)

            query_lower = query.lower()
            search_pattern = f"%{query_lower}%"

            result = await session.execute(
                select(BusinessTerm)
                .where(
                    and_(
                        or_(
                            BusinessTerm.connection_hash == connection_hash,
                            BusinessTerm.scope_type == SCOPE_GLOBAL,
                        ),
                        BusinessTerm.is_active == True,  # noqa: E712
                        or_(
                            BusinessTerm.term.ilike(search_pattern),
                            BusinessTerm.definition.ilike(search_pattern),
                        ),
                    )
                )
                .limit(limit)
            )
            terms = result.scalars().all()
            return [t.to_dict() for t in terms]

    async def increment_term_usage(self, term_id: str):
        """Increment usage count for a term"""
        async with get_db_session() as session:
            await session.execute(
                update(BusinessTerm)
                .where(BusinessTerm.id == term_id)
                .values(
                    usage_count=BusinessTerm.usage_count + 1,
                    last_used_at=datetime.utcnow(),
                )
            )

    # ============ Query Patterns CRUD ============

    async def add_query_pattern(
        self,
        connection_hash: str,
        natural_query: str,
        sql: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        complexity: Optional[str] = None,
        is_curated: bool = False,
        execution_time_ms: Optional[int] = None,
        result_count: Optional[int] = None,
        confidence_score: Optional[float] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Store a query pattern for few-shot learning.
        Can be auto-captured from successful queries or manually curated.
        """
        async with get_db_session() as session:
            # Check for duplicate (same connection + similar query)
            result = await session.execute(
                select(QueryPattern).where(
                    and_(
                        QueryPattern.connection_hash == connection_hash,
                        QueryPattern.natural_query.ilike(f"%{natural_query[:50]}%"),
                    )
                )
            )
            existing = result.scalar_one_or_none()

            if existing and not is_curated:
                # Update existing auto-captured pattern
                existing.success_count = (existing.success_count or 0) + 1
                existing.last_used_at = datetime.utcnow()
                if execution_time_ms:
                    existing.execution_time_ms = execution_time_ms
                await session.flush()
                return existing.to_dict()

            # Create new pattern
            pattern_id = str(uuid.uuid4())
            pattern = QueryPattern(
                id=pattern_id,
                connection_hash=connection_hash,
                natural_query=natural_query,
                sql=sql,
                description=description,
                tags=tags or [],
                complexity=complexity,
                is_curated=is_curated,
                execution_time_ms=execution_time_ms,
                result_count=result_count,
                confidence_score=confidence_score,  # type: ignore[arg-type]
                created_by=created_by,
                is_active=True,
            )
            session.add(pattern)
            await session.flush()

            # Index in vector DB
            self._index_pattern_in_vector_db(pattern)

            logger.debug(f"Stored query pattern: {natural_query[:50]}...")
            return pattern.to_dict()

    def _index_pattern_in_vector_db(self, pattern: QueryPattern):
        """Index a query pattern in vector DB (ChromaDB or Qdrant)"""
        try:
            collection = self._get_collection(self.COLLECTION_QUERY_PATTERNS)
            if collection is None:
                return

            doc_text = f"Question: {pattern.natural_query}\nSQL: {pattern.sql}"
            metadata = {
                "connection_hash": pattern.connection_hash,
                "natural_query": pattern.natural_query[:500] if pattern.natural_query else "",
                "sql": pattern.sql[:2000] if pattern.sql else "",
                "is_curated": pattern.is_curated,
            }

            vdb = self._get_vector_db()
            if vdb and vdb.db_type == "chromadb":
                collection.upsert(
                    ids=[pattern.id], documents=[doc_text], metadatas=[metadata]
                )
            elif vdb and vdb.db_type == "qdrant":
                embeddings = vdb._generate_embeddings([doc_text])
                if embeddings:
                    from qdrant_client.models import PointStruct

                    vdb.client.upsert(
                        collection_name=collection,
                        points=[
                            PointStruct(
                                id=hash(pattern.id) % (2**63),
                                vector=embeddings[0],
                                payload={
                                    **metadata,
                                    "document": doc_text,
                                    "id": pattern.id,
                                },
                            )
                        ],
                    )
        except Exception as e:
            logger.warning(f"Failed to index pattern in vector DB: {e}")

    async def get_query_pattern(self, pattern_id: str) -> Optional[Dict[str, Any]]:
        """Get a single query pattern by ID"""
        async with get_db_session() as session:
            result = await session.execute(
                select(QueryPattern).where(
                    and_(QueryPattern.id == pattern_id, QueryPattern.is_active == True)  # noqa: E712
                )
            )
            pattern = result.scalar_one_or_none()
            return pattern.to_dict() if pattern else None

    async def update_query_pattern(
        self, pattern_id: str, **updates
    ) -> Optional[Dict[str, Any]]:
        """Update a query pattern"""
        async with get_db_session() as session:
            result = await session.execute(
                select(QueryPattern).where(QueryPattern.id == pattern_id)
            )
            pattern = result.scalar_one_or_none()

            if not pattern:
                return None

            allowed_fields = {
                "natural_query",
                "sql",
                "description",
                "tags",
                "complexity",
                "is_curated",
                "rating",
                "is_active",
            }
            for field, value in updates.items():
                if field in allowed_fields and hasattr(pattern, field):
                    setattr(pattern, field, value)

            pattern.updated_at = datetime.utcnow()
            await session.flush()

            self._index_pattern_in_vector_db(pattern)
            return pattern.to_dict()

    async def delete_query_pattern(
        self, pattern_id: str, hard_delete: bool = False
    ) -> bool:
        """Delete a query pattern"""
        async with get_db_session() as session:
            if hard_delete:
                result = await session.execute(
                    delete(QueryPattern).where(QueryPattern.id == pattern_id)
                )
                await session.commit()
                return result.rowcount > 0  # type: ignore[attr-defined]
            else:
                result = await session.execute(
                    update(QueryPattern)
                    .where(QueryPattern.id == pattern_id)
                    .values(is_active=False, updated_at=datetime.utcnow())
                )
                await session.commit()
                return result.rowcount > 0  # type: ignore[attr-defined]

    async def list_query_patterns(
        self,
        connection_hash: str,
        is_curated: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        complexity: Optional[str] = None,
        min_rating: Optional[int] = None,
        include_inactive: bool = False,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List query patterns with filtering and pagination"""
        async with get_db_session() as session:
            conditions = [QueryPattern.connection_hash == connection_hash]

            if not include_inactive:
                conditions.append(QueryPattern.is_active == True)  # noqa: E712

            if is_curated is not None:
                conditions.append(QueryPattern.is_curated == is_curated)

            if complexity:
                conditions.append(QueryPattern.complexity == complexity)

            if min_rating is not None:
                conditions.append(QueryPattern.rating >= min_rating)

            if search:
                search_pattern = f"%{search}%"
                conditions.append(
                    or_(
                        QueryPattern.natural_query.ilike(search_pattern),
                        QueryPattern.sql.ilike(search_pattern),
                    )
                )

            # Count total
            count_query = select(func.count(QueryPattern.id)).where(and_(*conditions))
            total_result = await session.execute(count_query)
            total = total_result.scalar()

            # Fetch items
            query = (
                select(QueryPattern)
                .where(and_(*conditions))
                .order_by(QueryPattern.rating.desc(), QueryPattern.success_count.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(query)
            patterns = result.scalars().all()

            return {
                "items": [p.to_dict() for p in patterns],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def get_similar_queries(
        self, query: str, connection_hash: str, limit: int = 3
    ) -> List[Dict[str, str]]:
        """Find similar past queries as few-shot examples"""
        # Try semantic search first
        try:
            collection = self._get_collection(self.COLLECTION_QUERY_PATTERNS)
            vdb = self._get_vector_db()

            if collection and vdb:
                if vdb.db_type == "chromadb":
                    # Run sync ChromaDB call in executor to avoid blocking event loop
                    loop = asyncio.get_event_loop()
                    results = await loop.run_in_executor(
                        None,
                        lambda: collection.query(
                            query_texts=[query],
                            n_results=limit,
                            where={"connection_hash": connection_hash},
                        )
                    )

                    if results["metadatas"] and results["metadatas"][0]:
                        return [
                            {
                                "question": meta.get("natural_query", ""),
                                "sql": meta.get("sql", ""),
                            }
                            for meta in results["metadatas"][0]
                        ]

                elif vdb.db_type == "qdrant":
                    embeddings = vdb._generate_embeddings([query])
                    if embeddings:
                        from qdrant_client.models import (
                            FieldCondition,
                            Filter,
                            MatchValue,
                        )

                        results = vdb.client.query_points(
                            collection_name=collection,
                            query=embeddings[0],
                            query_filter=Filter(
                                must=[
                                    FieldCondition(
                                        key="connection_hash",
                                        match=MatchValue(value=connection_hash),
                                    )
                                ]
                            ),
                            limit=limit,
                        )

                        return [
                            {
                                "question": point.payload.get("natural_query", ""),
                                "sql": point.payload.get("sql", ""),
                            }
                            for point in results.points
                        ]

        except Exception as e:
            logger.warning(f"Similar query search failed: {e}")

        # Fallback: database query
        async with get_db_session() as session:
            result = await session.execute(
                select(QueryPattern)
                .where(
                    and_(
                        QueryPattern.connection_hash == connection_hash,
                        QueryPattern.is_active == True,  # noqa: E712
                    )
                )
                .order_by(QueryPattern.rating.desc())
                .limit(limit)
            )
            patterns = result.scalars().all()

            return [{"question": p.natural_query or "", "sql": p.sql or ""} for p in patterns]

    async def rate_query_pattern(self, pattern_id: str, rating: int):
        """Rate a query pattern (thumbs up/down)"""
        async with get_db_session() as session:
            result = await session.execute(
                select(QueryPattern).where(QueryPattern.id == pattern_id)
            )
            pattern = result.scalar_one_or_none()

            if pattern:
                # Rating: -1 to 5, where -1 is thumbs down
                pattern.rating = max(-1, min(5, rating))
                if rating > 0:
                    pattern.success_count = (pattern.success_count or 0) + 1
                else:
                    pattern.fail_count = (pattern.fail_count or 0) + 1
                await session.flush()

    # ============ Column Descriptions CRUD ============

    async def add_column_description(
        self,
        connection_hash: str,
        table_name: str,
        column_name: str,
        description: str,
        schema_name: Optional[str] = None,
        business_name: Optional[str] = None,
        data_type_hint: Optional[str] = None,
        allowed_values: Optional[List[str]] = None,
        sample_values: Optional[List[str]] = None,
        value_pattern: Optional[str] = None,
        is_pii: bool = False,
        is_sensitive: bool = False,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add semantic description to a column.

        Raises:
            ValueError: If description contains prompt injection patterns.
        """
        # Validate content fields for prompt injection
        _check_prompt_injection(description, "description")
        if business_name:
            _check_prompt_injection(business_name, "business_name")

        async with get_db_session() as session:
            col_id = ColumnDescription.generate_id(
                connection_hash, schema_name, table_name, column_name
            )

            # Check for existing
            result = await session.execute(
                select(ColumnDescription).where(ColumnDescription.id == col_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.description = description
                existing.business_name = business_name or existing.business_name
                existing.data_type_hint = data_type_hint or existing.data_type_hint
                existing.allowed_values = allowed_values or existing.allowed_values
                existing.sample_values = sample_values or existing.sample_values
                existing.value_pattern = value_pattern or existing.value_pattern
                existing.is_pii = is_pii
                existing.is_sensitive = is_sensitive
                existing.updated_at = datetime.utcnow()
                await session.flush()
                col_obj = existing
            else:
                # Create new
                col_obj = ColumnDescription(
                    id=col_id,
                    connection_hash=connection_hash,
                    schema_name=schema_name,
                    table_name=table_name,
                    column_name=column_name,
                    description=description,
                    business_name=business_name,
                    data_type_hint=data_type_hint,
                    allowed_values=allowed_values,
                    sample_values=sample_values,
                    value_pattern=value_pattern,
                    is_pii=is_pii,
                    is_sensitive=is_sensitive,
                    created_by=created_by,
                    is_active=True,
                )
                session.add(col_obj)
                await session.flush()

            # Index in vector DB
            self._index_column_in_vector_db(col_obj)

            return col_obj.to_dict()

    def _index_column_in_vector_db(self, col: ColumnDescription):
        """Index a column description in vector DB (ChromaDB or Qdrant)"""
        try:
            collection = self._get_collection(self.COLLECTION_COLUMN_DESC)
            if collection is None:
                return

            doc_text = f"Table: {col.table_name}\nColumn: {col.column_name}\nDescription: {col.description}"
            if col.business_name:
                doc_text += f"\nBusiness Name: {col.business_name}"

            metadata = {
                "connection_hash": col.connection_hash,
                "table_name": col.table_name,
                "column_name": col.column_name,
                "description": col.description[:500] if col.description else "",
            }

            vdb = self._get_vector_db()
            if vdb and vdb.db_type == "chromadb":
                collection.upsert(
                    ids=[col.id], documents=[doc_text], metadatas=[metadata]
                )
            elif vdb and vdb.db_type == "qdrant":
                embeddings = vdb._generate_embeddings([doc_text])
                if embeddings:
                    from qdrant_client.models import PointStruct

                    vdb.client.upsert(
                        collection_name=collection,
                        points=[
                            PointStruct(
                                id=hash(col.id) % (2**63),
                                vector=embeddings[0],
                                payload={
                                    **metadata,
                                    "document": doc_text,
                                    "id": col.id,
                                },
                            )
                        ],
                    )
        except Exception as e:
            logger.warning(f"Failed to index column in vector DB: {e}")

    async def get_column_description(self, col_id: str) -> Optional[Dict[str, Any]]:
        """Get a single column description by ID"""
        async with get_db_session() as session:
            result = await session.execute(
                select(ColumnDescription).where(
                    and_(
                        ColumnDescription.id == col_id,
                        ColumnDescription.is_active == True,  # noqa: E712
                    )
                )
            )
            col = result.scalar_one_or_none()
            return col.to_dict() if col else None

    async def update_column_description(
        self, col_id: str, **updates
    ) -> Optional[Dict[str, Any]]:
        """Update a column description.

        Raises:
            ValueError: If updated description or business_name contains prompt injection patterns.
        """
        # Validate content fields if they are being updated
        if "description" in updates and updates["description"]:
            _check_prompt_injection(updates["description"], "description")
        if "business_name" in updates and updates["business_name"]:
            _check_prompt_injection(updates["business_name"], "business_name")

        async with get_db_session() as session:
            result = await session.execute(
                select(ColumnDescription).where(ColumnDescription.id == col_id)
            )
            col = result.scalar_one_or_none()

            if not col:
                return None

            allowed_fields = {
                "description",
                "business_name",
                "data_type_hint",
                "allowed_values",
                "sample_values",
                "value_pattern",
                "is_pii",
                "is_sensitive",
                "is_active",
            }
            for field, value in updates.items():
                if field in allowed_fields and hasattr(col, field):
                    setattr(col, field, value)

            col.updated_at = datetime.utcnow()
            await session.flush()

            self._index_column_in_vector_db(col)
            return col.to_dict()

    async def delete_column_description(
        self, col_id: str, hard_delete: bool = False
    ) -> bool:
        """Delete a column description"""
        async with get_db_session() as session:
            if hard_delete:
                result = await session.execute(
                    delete(ColumnDescription).where(ColumnDescription.id == col_id)
                )
                await session.commit()
                return result.rowcount > 0  # type: ignore[attr-defined]
            else:
                result = await session.execute(
                    update(ColumnDescription)
                    .where(ColumnDescription.id == col_id)
                    .values(is_active=False, updated_at=datetime.utcnow())
                )
                await session.commit()
                return result.rowcount > 0  # type: ignore[attr-defined]

    async def list_column_descriptions(
        self,
        connection_hash: str,
        table_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        include_inactive: bool = False,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List column descriptions with filtering and pagination"""
        async with get_db_session() as session:
            conditions = [ColumnDescription.connection_hash == connection_hash]

            if not include_inactive:
                conditions.append(ColumnDescription.is_active == True)  # noqa: E712

            if table_name:
                conditions.append(ColumnDescription.table_name == table_name)

            if schema_name:
                conditions.append(ColumnDescription.schema_name == schema_name)

            if search:
                search_pattern = f"%{search}%"
                conditions.append(
                    or_(
                        ColumnDescription.column_name.ilike(search_pattern),
                        ColumnDescription.description.ilike(search_pattern),
                        ColumnDescription.business_name.ilike(search_pattern),
                    )
                )

            # Count total
            count_query = select(func.count(ColumnDescription.id)).where(
                and_(*conditions)
            )
            total_result = await session.execute(count_query)
            total = total_result.scalar()

            # Fetch items
            query = (
                select(ColumnDescription)
                .where(and_(*conditions))
                .order_by(ColumnDescription.table_name, ColumnDescription.column_name)
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(query)
            columns = result.scalars().all()

            return {
                "items": [c.to_dict() for c in columns],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def get_table_descriptions(
        self, connection_hash: str, table_name: str, schema_name: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Get all column descriptions for a table as a dict keyed by column name"""
        async with get_db_session() as session:
            conditions = [
                ColumnDescription.connection_hash == connection_hash,
                ColumnDescription.table_name == table_name,
                ColumnDescription.is_active == True,  # noqa: E712
            ]

            if schema_name:
                conditions.append(ColumnDescription.schema_name == schema_name)

            result = await session.execute(
                select(ColumnDescription).where(and_(*conditions))
            )
            columns = result.scalars().all()

            return {col.column_name or "": col.to_dict() for col in columns if col.column_name}

    async def get_column_context(
        self, query: str, connection_hash: str, table_names: Optional[List[str]] = None
    ) -> str:
        """
        Get relevant column descriptions formatted as context string.

        Two paths:

        - **Query-aware (B2)** — when ``FIX_QUERY_AWARE_COLUMN_CONTEXT``
          is True AND a non-empty query is provided AND the vector_db
          column-descriptions collection is reachable: semantic-search
          the column descriptions and return only the top
          ``MAX_COLUMNS_IN_CONTEXT`` matches. This addresses the audit's
          P0 #2 — the function ignoring its ``query`` parameter and
          returning every column for the connection (prompt pollution).
        - **Legacy dump** — anything else: return every active column
          description for the connection / table-scoped set, formatted
          identically. Unchanged behaviour from pre-B2.

        ``table_names``, when provided, is honoured by both paths
        (limits the legacy path to those tables; constrains the
        semantic candidate set in the query-aware path).
        """
        from app.core.config import settings

        use_query_aware = bool(
            settings.FIX_QUERY_AWARE_COLUMN_CONTEXT
            and query
            and query.strip()
        )

        if use_query_aware:
            ranked_ids = await self._search_relevant_columns(
                query=query,
                connection_hash=connection_hash,
                table_names=table_names,
                limit=settings.MAX_COLUMNS_IN_CONTEXT,
            )
            if ranked_ids:
                async with get_db_session() as session:
                    # Defense-in-depth: even though the vector search filters
                    # by connection_hash, repeat the predicate in SQL. The
                    # legacy fallback path below does the same — the
                    # query-aware path must NOT drop this guard. (Catches
                    # cross-tenant exposure if the vector index has stale
                    # metadata or a missing payload field.)
                    result = await session.execute(
                        select(ColumnDescription).where(
                            and_(
                                ColumnDescription.id.in_(ranked_ids),  # type: ignore[arg-type]
                                ColumnDescription.connection_hash == connection_hash,
                                ColumnDescription.is_active == True,  # noqa: E712
                            )
                        )
                    )
                    rows = result.scalars().all()
                # Preserve the vector_db's ranked order; SQL IN-set is unordered.
                order_index = {cid: i for i, cid in enumerate(ranked_ids)}
                ordered = sorted(
                    rows,
                    key=lambda c: order_index.get(c.id or "", len(ranked_ids)),
                )
                return self._format_columns(list(ordered))
            # Vector search returned nothing — fall through to the legacy
            # path so the caller still gets *some* signal rather than an
            # empty context (typical when the column collection isn't
            # indexed yet for this connection).

        async with get_db_session() as session:
            conditions = [
                ColumnDescription.connection_hash == connection_hash,
                ColumnDescription.is_active == True,  # noqa: E712
            ]

            if table_names:
                conditions.append(ColumnDescription.table_name.in_(table_names))

            result = await session.execute(
                select(ColumnDescription).where(and_(*conditions))  # type: ignore[arg-type]
            )
            columns = result.scalars().all()
            return self._format_columns(list(columns))

    @staticmethod
    def _format_columns(columns: List[ColumnDescription]) -> str:
        """Shared formatter so the legacy and query-aware paths produce
        identical output shape — the only difference is the SET of
        columns included."""
        if not columns:
            return ""
        descriptions = []
        for col in columns:
            desc = f"- {col.table_name}.{col.column_name}: {col.description}"
            if col.sample_values:
                desc += f" (examples: {', '.join(col.sample_values[:3])})"
            if col.is_pii:
                desc += " [PII]"
            descriptions.append(desc)
        return "Column Descriptions:\n" + "\n".join(descriptions)

    async def _search_relevant_columns(
        self,
        query: str,
        connection_hash: str,
        table_names: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[str]:
        """
        Rank column descriptions for the given (connection, optionally
        table-scoped) set by semantic similarity to the query. Returns
        the column-description IDs in descending relevance order.

        Returns an empty list on any failure path — the caller falls
        back to the legacy dump, so this method MUST NOT raise.

        Emits the `queryfyai_retrieval_fallback_total{reason=...}`
        Prometheus counter on every fallback path so operators can
        distinguish (a) vector_db unreachable, (b) no results matched
        the query, (c) an unexpected exception. Without this signal,
        retrieval-quality regressions look identical to a healthy
        idle deployment.
        """
        try:
            vdb = self._get_vector_db()
            if not vdb:
                _emit_retrieval_fallback("vector_db_unavailable")
                return []
            collection = self._get_collection(self.COLLECTION_COLUMN_DESC)
            if collection is None:
                _emit_retrieval_fallback("vector_db_unavailable")
                return []

            ranked_ids: List[str] = []
            if vdb.db_type == "chromadb":
                where_filter: Dict[str, Any] = {"connection_hash": connection_hash}
                if table_names:
                    where_filter = {
                        "$and": [
                            {"connection_hash": connection_hash},
                            {"table_name": {"$in": list(table_names)}},
                        ]
                    }
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: collection.query(
                        query_texts=[query],
                        n_results=max(limit, 1),
                        where=where_filter,
                    ),
                )
                if results.get("ids") and results["ids"][0]:
                    ranked_ids = list(results["ids"][0])
            elif vdb.db_type == "qdrant":
                from qdrant_client.models import (
                    FieldCondition,
                    Filter,
                    MatchAny,
                    MatchValue,
                )

                embeddings = vdb._generate_embeddings([query])
                if not embeddings:
                    _emit_retrieval_fallback("vector_db_unavailable")
                    return []
                # Use Any here so mypy doesn't insist on the broader
                # Qdrant condition union; runtime construction below
                # only ever appends FieldCondition.
                must: List[Any] = [
                    FieldCondition(
                        key="connection_hash",
                        match=MatchValue(value=connection_hash),
                    )
                ]
                if table_names:
                    must.append(
                        FieldCondition(
                            key="table_name",
                            match=MatchAny(any=list(table_names)),
                        )
                    )
                # Run sync Qdrant call in executor to avoid blocking
                # the event loop (P1 finding from Tier A.5 perf review).
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: vdb.client.query_points(
                        collection_name=collection,
                        query=embeddings[0],
                        query_filter=Filter(must=must),
                        limit=max(limit, 1),
                    ),
                )
                for point in response.points:
                    point_id = point.payload.get("id") if point.payload else None
                    if point_id:
                        ranked_ids.append(point_id)
            if not ranked_ids:
                _emit_retrieval_fallback("no_results")
            return ranked_ids[:limit]
        except Exception as e:
            logger.warning(f"_search_relevant_columns fell back: {e}")
            _emit_retrieval_fallback("exception")
            return []

    # ============ Bulk Import/Export ============

    async def bulk_import_terms(
        self,
        connection_hash: str,
        terms: List[Dict[str, Any]],
        file_name: Optional[str] = None,
        file_format: Optional[str] = None,
        imported_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bulk import business terms"""
        async with get_db_session() as session:
            created = 0
            updated = 0
            failed = 0
            errors = []

            for i, term_data in enumerate(terms):
                try:
                    # Validate required fields
                    if not all(
                        k in term_data for k in ["term", "definition", "sql_expression"]
                    ):
                        errors.append(
                            {
                                "row": i + 1,
                                "error": "Missing required fields: term, definition, sql_expression",
                            }
                        )
                        failed += 1
                        continue

                    # Validate content for prompt injection
                    try:
                        _check_prompt_injection(term_data["definition"], "definition")
                        _check_prompt_injection(term_data["sql_expression"], "sql_expression")
                    except ValueError as ve:
                        errors.append({"row": i + 1, "error": str(ve)})
                        failed += 1
                        continue

                    # Generate ID
                    scope_type = term_data.get("scope_type", SCOPE_DATABASE)
                    scope_key = term_data.get("scope_key")
                    id_source = f"{connection_hash}_{scope_type}_{scope_key or ''}_{term_data['term'].lower()}"
                    term_id = hashlib.sha256(id_source.encode()).hexdigest()[:64]

                    # Check existing
                    result = await session.execute(
                        select(BusinessTerm).where(BusinessTerm.id == term_id)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.definition = term_data["definition"]
                        existing.sql_expression = term_data["sql_expression"]
                        existing.synonyms = term_data.get("synonyms", existing.synonyms)
                        existing.examples = term_data.get("examples", existing.examples)
                        existing.category = term_data.get("category", existing.category)
                        existing.updated_at = datetime.utcnow()
                        updated += 1
                    else:
                        term = BusinessTerm(
                            id=term_id,
                            connection_hash=connection_hash,
                            term=term_data["term"],
                            definition=term_data["definition"],
                            sql_expression=term_data["sql_expression"],
                            scope_type=scope_type,
                            scope_key=scope_key,
                            synonyms=term_data.get("synonyms", []),
                            examples=term_data.get("examples", []),
                            category=term_data.get("category"),
                            created_by=imported_by,
                            is_active=True,
                        )
                        session.add(term)
                        created += 1

                except Exception as e:
                    errors.append({"row": i + 1, "error": str(e)})
                    failed += 1

            await session.flush()

            # Record import history
            history = ImportHistory(
                connection_hash=connection_hash,
                import_type="terms",
                file_name=file_name,
                file_format=file_format,
                records_total=len(terms),
                records_created=created,
                records_updated=updated,
                records_failed=failed,
                error_details=errors if errors else None,
                imported_by=imported_by,
            )
            session.add(history)
            await session.flush()

            return {
                "total": len(terms),
                "created": created,
                "updated": updated,
                "failed": failed,
                "errors": errors,
                "import_id": history.id,
            }

    async def bulk_import_column_descriptions(
        self,
        connection_hash: str,
        descriptions: List[Dict[str, Any]],
        file_name: Optional[str] = None,
        file_format: Optional[str] = None,
        imported_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bulk import column descriptions"""
        async with get_db_session() as session:
            created = 0
            updated = 0
            failed = 0
            errors = []

            for i, desc_data in enumerate(descriptions):
                try:
                    if not all(
                        k in desc_data
                        for k in ["table_name", "column_name", "description"]
                    ):
                        errors.append(
                            {
                                "row": i + 1,
                                "error": "Missing required fields: table_name, column_name, description",
                            }
                        )
                        failed += 1
                        continue

                    # Validate content for prompt injection
                    try:
                        _check_prompt_injection(desc_data["description"], "description")
                        if desc_data.get("business_name"):
                            _check_prompt_injection(desc_data["business_name"], "business_name")
                    except ValueError as ve:
                        errors.append({"row": i + 1, "error": str(ve)})
                        failed += 1
                        continue

                    schema_name = desc_data.get("schema_name")
                    col_id = ColumnDescription.generate_id(
                        connection_hash,
                        schema_name,
                        desc_data["table_name"],
                        desc_data["column_name"],
                    )

                    result = await session.execute(
                        select(ColumnDescription).where(ColumnDescription.id == col_id)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.description = desc_data["description"]
                        existing.business_name = desc_data.get(
                            "business_name", existing.business_name
                        )
                        existing.data_type_hint = desc_data.get(
                            "data_type_hint", existing.data_type_hint
                        )
                        existing.allowed_values = desc_data.get(
                            "allowed_values", existing.allowed_values
                        )
                        existing.sample_values = desc_data.get(
                            "sample_values", existing.sample_values
                        )
                        existing.is_pii = desc_data.get("is_pii", existing.is_pii)
                        existing.is_sensitive = desc_data.get(
                            "is_sensitive", existing.is_sensitive
                        )
                        existing.updated_at = datetime.utcnow()
                        updated += 1
                    else:
                        col = ColumnDescription(
                            id=col_id,
                            connection_hash=connection_hash,
                            schema_name=schema_name,
                            table_name=desc_data["table_name"],
                            column_name=desc_data["column_name"],
                            description=desc_data["description"],
                            business_name=desc_data.get("business_name"),
                            data_type_hint=desc_data.get("data_type_hint"),
                            allowed_values=desc_data.get("allowed_values"),
                            sample_values=desc_data.get("sample_values"),
                            is_pii=desc_data.get("is_pii", False),
                            is_sensitive=desc_data.get("is_sensitive", False),
                            created_by=imported_by,
                            is_active=True,
                        )
                        session.add(col)
                        created += 1

                except Exception as e:
                    errors.append({"row": i + 1, "error": str(e)})
                    failed += 1

            await session.flush()

            history = ImportHistory(
                connection_hash=connection_hash,
                import_type="columns",
                file_name=file_name,
                file_format=file_format,
                records_total=len(descriptions),
                records_created=created,
                records_updated=updated,
                records_failed=failed,
                error_details=errors if errors else None,
                imported_by=imported_by,
            )
            session.add(history)
            await session.flush()

            return {
                "total": len(descriptions),
                "created": created,
                "updated": updated,
                "failed": failed,
                "errors": errors,
                "import_id": history.id,
            }

    async def get_import_history(
        self, connection_hash: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get recent import history"""
        async with get_db_session() as session:
            result = await session.execute(
                select(ImportHistory)
                .where(ImportHistory.connection_hash == connection_hash)
                .order_by(ImportHistory.imported_at.desc())
                .limit(limit)
            )
            history = result.scalars().all()
            return [h.to_dict() for h in history]

    # ============ Context Building ============

    async def build_query_context(
        self,
        query: str,
        connection_hash: str,
        schema: str,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Build enhanced context for LLM by combining:
        - Relevant business terms
        - Similar past queries (few-shot examples)
        - Column descriptions
        - Original schema
        """
        context_parts = []

        # 1. Business terms
        terms = await self.get_relevant_terms(
            query=query,
            connection_hash=connection_hash,
            tenant_id=tenant_id,
            session_id=session_id,
            limit=5,
        )

        if terms:
            terms_text = "## Business Terms\n"
            for term in terms:
                terms_text += f"- **{term['term']}**: {term['definition']}\n"
                terms_text += f"  SQL: `{term['sql_expression']}`\n"
            context_parts.append(terms_text)

        # 2. Similar queries (few-shot examples)
        similar = await self.get_similar_queries(query, connection_hash, limit=3)
        if similar:
            examples_text = "## Similar Queries (Examples)\n"
            for i, ex in enumerate(similar, 1):
                examples_text += f"### Example {i}\n"
                examples_text += f"Question: {ex['question']}\n"
                examples_text += f"```sql\n{ex['sql']}\n```\n\n"
            context_parts.append(examples_text)

        # 3. Column descriptions
        col_context = await self.get_column_context(query, connection_hash)
        if col_context:
            context_parts.append(col_context)

        # 4. Schema (always included)
        context_parts.append(f"## Database Schema\n{schema}")

        return "\n\n".join(context_parts)

    # ============ Stats & Management ============

    async def get_stats(self, connection_hash: Optional[str] = None) -> Dict[str, Any]:
        """Get data dictionary statistics"""
        async with get_db_session() as session:
            conditions_terms = [BusinessTerm.is_active == True]  # noqa: E712
            conditions_patterns = [QueryPattern.is_active == True]  # noqa: E712
            conditions_columns = [ColumnDescription.is_active == True]  # noqa: E712

            if connection_hash:
                conditions_terms.append(
                    or_(
                        BusinessTerm.connection_hash == connection_hash,
                        BusinessTerm.scope_type == SCOPE_GLOBAL,
                    )
                )
                conditions_patterns.append(
                    QueryPattern.connection_hash == connection_hash
                )
                conditions_columns.append(
                    ColumnDescription.connection_hash == connection_hash
                )

            # Count terms
            terms_result = await session.execute(
                select(func.count(BusinessTerm.id)).where(and_(*conditions_terms))  # type: ignore[arg-type]
            )
            total_terms = terms_result.scalar()

            # Count patterns
            patterns_result = await session.execute(
                select(func.count(QueryPattern.id)).where(and_(*conditions_patterns))  # type: ignore[arg-type]
            )
            total_patterns = patterns_result.scalar()

            # Count columns
            columns_result = await session.execute(
                select(func.count(ColumnDescription.id)).where(
                    and_(*conditions_columns)  # type: ignore[arg-type]
                )
            )
            total_columns = columns_result.scalar()

            # Count curated patterns
            curated_result = await session.execute(
                select(func.count(QueryPattern.id)).where(
                    and_(*conditions_patterns, QueryPattern.is_curated == True)  # type: ignore[arg-type]  # noqa: E712
                )
            )
            curated_patterns = curated_result.scalar()

            return {
                "total_terms": total_terms,
                "total_patterns": total_patterns,
                "total_columns": total_columns,
                "curated_patterns": curated_patterns,
            }

    async def clear_session_data(self, session_id: str):
        """Clear all session-level business terms"""
        async with get_db_session() as session:
            await session.execute(
                delete(BusinessTerm).where(
                    and_(
                        BusinessTerm.scope_type == SCOPE_SESSION,
                        BusinessTerm.scope_key == session_id,
                    )
                )
            )
            logger.debug(f"Cleared session data for {session_id}")


# Global instance
data_dictionary = DataDictionaryService()
