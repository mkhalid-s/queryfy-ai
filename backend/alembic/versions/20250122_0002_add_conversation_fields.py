"""Add conversation persistence fields to query_history

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-22

Adds fields for:
- Analyst mode responses (answer, key_findings, confidence, chart_spec)
- Result summary for restore (raw_result_summary)
- Agent execution metadata (tools_used, agent_steps)
- Conversation threading (is_follow_up, conversation_turn, session_id)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if query_history table exists first
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "query_history" not in tables:
        # Create the table if it doesn't exist
        op.create_table(
            "query_history",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("connection_hash", sa.String(16), nullable=False, index=True),
            sa.Column("natural_query", sa.Text(), nullable=False),
            sa.Column("sanitized_query", sa.Text(), nullable=True),
            sa.Column("sql", sa.Text(), nullable=False),
            sa.Column("sql_hash", sa.String(64), nullable=True),
            sa.Column("db_type", sa.String(20), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("execution_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("last_executed_at", sa.DateTime(), nullable=True),
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("feedback_rating", sa.Integer(), nullable=True),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            # Analyst mode fields
            sa.Column("mode", sa.String(20), nullable=True, server_default="standard"),
            sa.Column("answer", sa.Text(), nullable=True),
            sa.Column("key_findings", postgresql.JSONB(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("chart_spec", postgresql.JSONB(), nullable=True),
            sa.Column("raw_result_summary", postgresql.JSONB(), nullable=True),
            sa.Column("tools_used", postgresql.JSONB(), nullable=True),
            sa.Column("agent_steps", postgresql.JSONB(), nullable=True),
            # Conversation threading
            sa.Column("is_follow_up", sa.Boolean(), nullable=True, server_default="false"),
            sa.Column("conversation_turn", sa.Integer(), nullable=True),
            sa.Column("session_id", sa.String(64), nullable=True),
        )
        # Create indexes
        op.create_index("ix_query_history_conn_created", "query_history", ["connection_hash", "created_at"])
        op.create_index("ix_query_history_conn_pinned", "query_history", ["connection_hash", "pinned"])
        op.create_index("ix_query_history_conn_db", "query_history", ["connection_hash", "db_type"])
        op.create_index("ix_query_history_session", "query_history", ["session_id", "created_at"])
    else:
        # Add new columns to existing table
        existing_columns = [col["name"] for col in inspector.get_columns("query_history")]

        # Analyst mode fields
        if "mode" not in existing_columns:
            op.add_column("query_history", sa.Column("mode", sa.String(20), nullable=True, server_default="standard"))
        if "answer" not in existing_columns:
            op.add_column("query_history", sa.Column("answer", sa.Text(), nullable=True))
        if "key_findings" not in existing_columns:
            op.add_column("query_history", sa.Column("key_findings", postgresql.JSONB(), nullable=True))
        if "confidence" not in existing_columns:
            op.add_column("query_history", sa.Column("confidence", sa.Float(), nullable=True))
        if "chart_spec" not in existing_columns:
            op.add_column("query_history", sa.Column("chart_spec", postgresql.JSONB(), nullable=True))
        if "raw_result_summary" not in existing_columns:
            op.add_column("query_history", sa.Column("raw_result_summary", postgresql.JSONB(), nullable=True))
        if "tools_used" not in existing_columns:
            op.add_column("query_history", sa.Column("tools_used", postgresql.JSONB(), nullable=True))
        if "agent_steps" not in existing_columns:
            op.add_column("query_history", sa.Column("agent_steps", postgresql.JSONB(), nullable=True))

        # Conversation threading fields
        if "is_follow_up" not in existing_columns:
            op.add_column("query_history", sa.Column("is_follow_up", sa.Boolean(), nullable=True, server_default="false"))
        if "conversation_turn" not in existing_columns:
            op.add_column("query_history", sa.Column("conversation_turn", sa.Integer(), nullable=True))
        if "session_id" not in existing_columns:
            op.add_column("query_history", sa.Column("session_id", sa.String(64), nullable=True))

        # Create session index if it doesn't exist
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("query_history")]
        if "ix_query_history_session" not in existing_indexes:
            op.create_index("ix_query_history_session", "query_history", ["session_id", "created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Drop session index
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("query_history")]
    if "ix_query_history_session" in existing_indexes:
        op.drop_index("ix_query_history_session", table_name="query_history")

    # Drop new columns
    existing_columns = [col["name"] for col in inspector.get_columns("query_history")]
    columns_to_drop = [
        "mode", "answer", "key_findings", "confidence", "chart_spec",
        "raw_result_summary", "tools_used", "agent_steps",
        "is_follow_up", "conversation_turn", "session_id"
    ]
    for col in columns_to_drop:
        if col in existing_columns:
            op.drop_column("query_history", col)
