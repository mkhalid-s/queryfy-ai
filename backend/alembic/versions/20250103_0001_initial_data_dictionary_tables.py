"""Initial data dictionary tables

Revision ID: 0001
Revises:
Create Date: 2025-01-03

Creates tables for:
- business_terms: Business term definitions
- query_patterns: Successful query patterns for few-shot learning
- column_descriptions: Semantic column descriptions
- import_history: Audit trail for bulk imports
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create business_terms table
    op.create_table(
        "business_terms",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("connection_hash", sa.String(16), nullable=False, index=True),
        sa.Column("term", sa.String(255), nullable=False, index=True),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("sql_expression", sa.Text(), nullable=False),
        sa.Column(
            "scope_type", sa.String(20), nullable=False, server_default="database"
        ),
        sa.Column("scope_key", sa.String(255), nullable=True),
        sa.Column("synonyms", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("examples", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true", index=True
        ),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # Create composite indexes for business_terms
    op.create_index(
        "ix_business_terms_conn_term", "business_terms", ["connection_hash", "term"]
    )
    op.create_index(
        "ix_business_terms_scope", "business_terms", ["scope_type", "scope_key"]
    )
    op.create_index(
        "ix_business_terms_active", "business_terms", ["connection_hash", "is_active"]
    )

    # Create query_patterns table
    op.create_table(
        "query_patterns",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("connection_hash", sa.String(16), nullable=False, index=True),
        sa.Column("natural_query", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("complexity", sa.String(20), nullable=True),
        sa.Column(
            "is_curated",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            index=True,
        ),
        sa.Column("rating", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true", index=True
        ),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # Create composite indexes for query_patterns
    op.create_index(
        "ix_query_patterns_conn_curated",
        "query_patterns",
        ["connection_hash", "is_curated"],
    )
    op.create_index(
        "ix_query_patterns_rating", "query_patterns", ["connection_hash", "rating"]
    )
    op.create_index(
        "ix_query_patterns_active", "query_patterns", ["connection_hash", "is_active"]
    )

    # Create column_descriptions table
    op.create_table(
        "column_descriptions",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("connection_hash", sa.String(16), nullable=False, index=True),
        sa.Column("schema_name", sa.String(255), nullable=True),
        sa.Column("table_name", sa.String(255), nullable=False, index=True),
        sa.Column("column_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("business_name", sa.String(255), nullable=True),
        sa.Column("data_type_hint", sa.String(100), nullable=True),
        sa.Column("allowed_values", postgresql.JSONB(), nullable=True),
        sa.Column("sample_values", postgresql.JSONB(), nullable=True),
        sa.Column("value_pattern", sa.String(255), nullable=True),
        sa.Column("is_pii", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true", index=True
        ),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # Create composite indexes for column_descriptions
    op.create_index(
        "ix_column_desc_conn_table",
        "column_descriptions",
        ["connection_hash", "table_name"],
    )
    op.create_index(
        "ix_column_desc_active", "column_descriptions", ["connection_hash", "is_active"]
    )

    # Create import_history table
    op.create_table(
        "import_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("connection_hash", sa.String(16), nullable=False, index=True),
        sa.Column("import_type", sa.String(20), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_format", sa.String(10), nullable=True),
        sa.Column("records_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_details", postgresql.JSONB(), nullable=True),
        sa.Column("imported_by", sa.String(255), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Create composite index for import_history
    op.create_index(
        "ix_import_history_conn", "import_history", ["connection_hash", "imported_at"]
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("import_history")
    op.drop_table("column_descriptions")
    op.drop_table("query_patterns")
    op.drop_table("business_terms")
