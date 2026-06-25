"""
QueryfyAI - SQLAlchemy ORM Models

Database models for Data Dictionary persistence:
- BusinessTerm: Business term definitions (e.g., "revenue" = sales - refunds)
- QueryPattern: Successful query patterns for few-shot learning
- ColumnDescription: Semantic column descriptions
- ImportHistory: Audit trail for bulk imports
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


def generate_uuid() -> str:
    """Generate a UUID string for primary keys."""
    return str(uuid.uuid4())


class BusinessTerm(Base):
    """
    Business term definitions.

    Maps business language to SQL expressions.
    Example: "revenue" = SUM(orders.amount) - SUM(refunds.amount)
    """

    __tablename__ = "business_terms"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    connection_hash = Column(String(16), nullable=False, index=True)

    # Term definition
    term = Column(String(255), nullable=False, index=True)
    definition = Column(Text, nullable=False)
    sql_expression = Column(Text, nullable=False)

    # Scope: global, database, tenant, session
    scope_type = Column(String(20), nullable=False, default="database")
    scope_key = Column(String(255), nullable=True)  # tenant_id or session_id

    # Metadata
    synonyms = Column(JSONB, default=list)  # ["sales", "income"]
    examples = Column(JSONB, default=list)  # ["Show revenue for Q1"]
    category = Column(String(100), nullable=True)  # "financial", "metrics"

    # Usage tracking
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)

    # Soft delete and audit
    is_active = Column(Boolean, default=True, index=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index("ix_business_terms_conn_term", "connection_hash", "term"),
        Index("ix_business_terms_scope", "scope_type", "scope_key"),
        Index("ix_business_terms_active", "connection_hash", "is_active"),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "connection_hash": self.connection_hash,
            "term": self.term,
            "definition": self.definition,
            "sql_expression": self.sql_expression,
            "scope_type": self.scope_type,
            "scope_key": self.scope_key,
            "synonyms": self.synonyms or [],
            "examples": self.examples or [],
            "category": self.category,
            "usage_count": self.usage_count,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class QueryPattern(Base):
    """
    Successful query patterns for few-shot learning.

    Stores natural language → SQL mappings that worked well.
    Can be auto-captured or manually curated.
    """

    __tablename__ = "query_patterns"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    connection_hash = Column(String(16), nullable=False, index=True)

    # Query mapping
    natural_query = Column(Text, nullable=False)
    sql = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    # Categorization
    tags = Column(JSONB, default=list)  # ["aggregation", "join", "time-series"]
    complexity = Column(String(20), nullable=True)  # simple, medium, complex

    # Quality signals
    is_curated = Column(Boolean, default=False, index=True)  # Manual vs auto-captured
    rating = Column(Integer, default=0)  # User feedback (-1 to 5)
    confidence_score = Column(Float, nullable=True)  # LLM confidence if available

    # Performance metrics
    execution_time_ms = Column(Integer, nullable=True)
    result_count = Column(Integer, nullable=True)

    # Usage tracking
    success_count = Column(Integer, default=1)
    fail_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)

    # Soft delete and audit
    is_active = Column(Boolean, default=True, index=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index("ix_query_patterns_conn_curated", "connection_hash", "is_curated"),
        Index("ix_query_patterns_rating", "connection_hash", "rating"),
        Index("ix_query_patterns_active", "connection_hash", "is_active"),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "connection_hash": self.connection_hash,
            "natural_query": self.natural_query,
            "sql": self.sql,
            "description": self.description,
            "tags": self.tags or [],
            "complexity": self.complexity,
            "is_curated": self.is_curated,
            "rating": self.rating,
            "execution_time_ms": self.execution_time_ms,
            "result_count": self.result_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": (
                self.last_used_at.isoformat() if self.last_used_at else None
            ),
        }


class ColumnDescription(Base):
    """
    Semantic column descriptions.

    Provides additional context about database columns
    beyond what's in the schema (type, nullable, etc.).
    """

    __tablename__ = "column_descriptions"

    # Composite key: connection_hash + table + column
    id = Column(String(255), primary_key=True)  # {conn_hash}_{schema}_{table}_{column}
    connection_hash = Column(String(16), nullable=False, index=True)

    # Column identification
    schema_name = Column(String(255), nullable=True)  # PostgreSQL schema
    table_name = Column(String(255), nullable=False, index=True)
    column_name = Column(String(255), nullable=False)

    # Semantic information
    description = Column(Text, nullable=False)
    business_name = Column(String(255), nullable=True)  # Friendly name: "Customer ID"
    data_type_hint = Column(
        String(100), nullable=True
    )  # "currency", "percentage", "email"

    # Value information
    allowed_values = Column(JSONB, nullable=True)  # ["active", "inactive", "pending"]
    sample_values = Column(JSONB, nullable=True)  # ["john@ex.com", "jane@corp.io"]
    value_pattern = Column(String(255), nullable=True)  # Regex pattern if applicable

    # Data sensitivity
    is_pii = Column(Boolean, default=False)  # Personal identifiable information
    is_sensitive = Column(Boolean, default=False)  # Other sensitive data

    # Soft delete and audit
    is_active = Column(Boolean, default=True, index=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index("ix_column_desc_conn_table", "connection_hash", "table_name"),
        Index("ix_column_desc_active", "connection_hash", "is_active"),
    )

    @staticmethod
    def generate_id(
        connection_hash: str,
        schema_name: Optional[str],
        table_name: str,
        column_name: str,
    ) -> str:
        """Generate composite ID for a column description."""
        schema_part = schema_name or "default"
        return f"{connection_hash}_{schema_part}_{table_name}_{column_name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "connection_hash": self.connection_hash,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "description": self.description,
            "business_name": self.business_name,
            "data_type_hint": self.data_type_hint,
            "allowed_values": self.allowed_values,
            "sample_values": self.sample_values,
            "is_pii": self.is_pii,
            "is_sensitive": self.is_sensitive,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class QueryHistory(Base):
    """
    Long-term query history for cross-session re-execution.

    Stores query execution records beyond session expiry.
    Enables users to re-execute queries after logging out and back in.

    Security:
    - connection_hash ensures queries only run on the same database
    - db_type prevents cross-database SQL execution
    - sql is stored server-side, never trusted from client
    """

    __tablename__ = "query_history"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    connection_hash = Column(String(16), nullable=False, index=True)

    # Query data
    natural_query = Column(Text, nullable=False)  # User's question
    sanitized_query = Column(Text, nullable=True)  # Cleaned version
    sql = Column(Text, nullable=False)  # Generated SQL
    sql_hash = Column(String(64), nullable=True)  # HMAC for integrity (session-bound)
    db_type = Column(String(20), nullable=False)  # postgresql, mysql, sqlite, etc.

    # Execution tracking
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    execution_count = Column(Integer, default=1)
    last_executed_at = Column(DateTime, nullable=True)

    # User interaction
    pinned = Column(Boolean, default=False, index=True)
    feedback_rating = Column(Integer, nullable=True)  # -1 to 5
    explanation = Column(Text, nullable=True)  # AI explanation of the SQL

    # Analyst mode fields
    mode = Column(String(20), nullable=True, default="standard")  # 'standard' or 'analyst'
    answer = Column(Text, nullable=True)  # Analyst mode synthesized answer
    key_findings = Column(JSONB, nullable=True)  # Array of insights
    confidence = Column(Float, nullable=True)  # 0-1 confidence score
    chart_spec = Column(JSONB, nullable=True)  # Chart configuration with data
    raw_result_summary = Column(JSONB, nullable=True)  # {columns, row_count, sample_rows}
    tools_used = Column(JSONB, nullable=True)  # Array of tool names
    agent_steps = Column(JSONB, nullable=True)  # Array of step objects

    # Conversation threading
    is_follow_up = Column(Boolean, default=False)
    conversation_turn = Column(Integer, nullable=True)
    session_id = Column(String(64), nullable=True, index=True)

    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes for efficient queries
    __table_args__ = (
        Index("ix_query_history_conn_created", "connection_hash", "created_at"),
        Index("ix_query_history_conn_pinned", "connection_hash", "pinned"),
        Index("ix_query_history_conn_db", "connection_hash", "db_type"),
        Index("ix_query_history_session", "session_id", "created_at"),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "connection_hash": self.connection_hash,
            "query": self.natural_query,
            "sanitized_query": self.sanitized_query,
            "sql": self.sql,
            "sql_hash": self.sql_hash,
            "db_type": self.db_type,
            "success": self.success,
            "error_message": self.error_message,
            "execution_count": self.execution_count,
            "pinned": self.pinned,
            "feedback_rating": self.feedback_rating,
            "explanation": self.explanation,
            # Analyst mode fields
            "mode": self.mode,
            "answer": self.answer,
            "key_findings": self.key_findings or [],
            "confidence": self.confidence,
            "chart_spec": self.chart_spec,
            "raw_result_summary": self.raw_result_summary,
            "tools_used": self.tools_used or [],
            "agent_steps": self.agent_steps or [],
            # Conversation threading
            "is_follow_up": self.is_follow_up,
            "conversation_turn": self.conversation_turn,
            "session_id": self.session_id,
            # Timestamps
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_executed_at": (
                self.last_executed_at.isoformat() if self.last_executed_at else None
            ),
        }

    def to_history_entry(self) -> dict:
        """Convert to session history entry format for compatibility."""
        return {
            "id": self.id,
            "query": self.natural_query,
            "sanitized_query": self.sanitized_query,
            "sql": self.sql,
            "sql_hash": self.sql_hash,
            "db_type": self.db_type,
            "connection_id": self.connection_hash,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
            "success": self.success,
            "error_message": self.error_message,
            "pinned": self.pinned,
            "feedback_rating": self.feedback_rating,
            "explanation": self.explanation,
            # Analyst mode fields
            "mode": self.mode,
            "answer": self.answer,
            "key_findings": self.key_findings or [],
            "confidence": self.confidence,
            "chart_spec": self.chart_spec,
            "raw_result_summary": self.raw_result_summary,
            "tools_used": self.tools_used or [],
            "agent_steps": self.agent_steps or [],
            # Conversation threading
            "is_follow_up": self.is_follow_up,
            "conversation_turn": self.conversation_turn,
            "session_id": self.session_id,
        }


class ImportHistory(Base):
    """
    Audit trail for bulk imports.

    Tracks CSV/JSON/Excel imports for data dictionary entries.
    """

    __tablename__ = "import_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_hash = Column(String(16), nullable=False, index=True)

    # Import details
    import_type = Column(String(20), nullable=False)  # terms, patterns, columns
    file_name = Column(String(255), nullable=True)
    file_format = Column(String(10), nullable=True)  # csv, json, xlsx

    # Results
    records_total = Column(Integer, default=0)
    records_created = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)
    error_details = Column(JSONB, nullable=True)  # Row-level errors

    # Audit
    imported_by = Column(String(255), nullable=True)
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Indexes
    __table_args__ = (
        Index("ix_import_history_conn", "connection_hash", "imported_at"),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "connection_hash": self.connection_hash,
            "import_type": self.import_type,
            "file_name": self.file_name,
            "file_format": self.file_format,
            "records_total": self.records_total,
            "records_created": self.records_created,
            "records_updated": self.records_updated,
            "records_failed": self.records_failed,
            "error_details": self.error_details,
            "imported_by": self.imported_by,
            "imported_at": self.imported_at.isoformat() if self.imported_at else None,
        }
