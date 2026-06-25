"""
QueryfyAI - Tool Definitions

JSON Schema definitions for all available tools.
Compatible with OpenAI, Anthropic, and MCP formats.
"""

from app.services.tools.registry import ToolDefinition

# =============================================================================
# SCHEMA TOOLS - For exploring database structure
# =============================================================================

SEARCH_TABLES = ToolDefinition(
    name="search_tables",
    description="""Search for database tables relevant to a query.
Returns SCHEMA-QUALIFIED table names (e.g., 'schema.table' for PostgreSQL, 'keyspace.table' for Cassandra).

IMPORTANT: Always use the full qualified name returned by this tool in your SQL queries.

For NoSQL databases (Cassandra, DynamoDB), also returns partition key information which is REQUIRED in WHERE clauses.

Example (PostgreSQL):
- Input: "policy"
- Output: demoapp.policies, demoapp.policy_holders (use these names in SQL)

Example (Cassandra):
- Input: "orders"
- Output: ecommerce.orders (Partition Key: order_id - REQUIRED in WHERE)""",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term to find relevant tables (e.g., 'customer', 'order', 'revenue')"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of tables to return",
                "default": 5
            }
        },
        "required": ["query"]
    }
)

GET_TABLE_SCHEMA = ToolDefinition(
    name="get_table_schema",
    description="""Get detailed schema for a specific table.
Returns column names, data types, nullable status, foreign keys, and the QUALIFIED NAME to use in queries.

Accepts both simple names ("users") or qualified names ("public.users").
Returns the full schema-qualified name you should use in SQL queries.

For NoSQL databases, also returns partition/clustering keys which are REQUIRED in queries.

Example (PostgreSQL):
- Input: "policies"
- Output: Schema for 'demoapp.policies': Use this name in queries: demoapp.policies
  Columns: policy_id (bigint, PK), holder_name (varchar), amount (decimal)...

Example (Cassandra):
- Input: "orders"
- Output: Schema for 'ecommerce.orders'
  Partition Keys (REQUIRED in WHERE): order_id
  Clustering Keys: created_at""",
    parameters={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Name of the table (can be 'table' or 'schema.table')"
            },
            "include_sample_values": {
                "type": "boolean",
                "description": "Whether to include sample values for each column",
                "default": False
            }
        },
        "required": ["table_name"]
    }
)


# =============================================================================
# BUSINESS TOOLS - For understanding domain context
# =============================================================================

LOOKUP_BUSINESS_TERM = ToolDefinition(
    name="lookup_business_term",
    description="""Look up a business term's definition and SQL expression.
Use this for domain-specific terms like 'revenue', 'churn rate', 'ARR', 'active user'.
Returns the SQL expression that defines the term.

Example:
- Input: "revenue"
- Output: revenue = SUM(orders.amount) - SUM(refunds.amount) WHERE status = 'completed'""",
    parameters={
        "type": "object",
        "properties": {
            "term": {
                "type": "string",
                "description": "Business term to look up (e.g., 'revenue', 'churn', 'ARR')"
            }
        },
        "required": ["term"]
    }
)


# =============================================================================
# QUERY TOOLS - For SQL execution and examples
# =============================================================================

FIND_SIMILAR_QUERIES = ToolDefinition(
    name="find_similar_queries",
    description="""Find previously successful queries similar to the current question.
Returns natural language questions with their SQL implementations.
Use this to learn from past examples before writing new SQL.

Example:
- Input: "top customers"
- Output:
  Q: "Show me top 10 customers by total spend"
  SQL: SELECT c.name, SUM(o.amount) FROM customers c JOIN orders o...

  Q: "Who are our best customers this year?"
  SQL: SELECT customer_id, COUNT(*) FROM orders WHERE year = 2024...""",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The natural language question to find similar queries for"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of similar queries to return",
                "default": 3
            }
        },
        "required": ["query"]
    }
)

EXECUTE_SQL = ToolDefinition(
    name="execute_sql",
    description="""Execute a SQL query and return results.
Only use after you've verified the schema and are confident the query is correct.
Returns column names and data rows.

IMPORTANT RULES:
1. Only SELECT queries are allowed. No INSERT, UPDATE, DELETE, or DDL.
2. ALWAYS use schema-qualified table names (e.g., 'demoapp.policies' not 'policies').
3. For Cassandra: Include partition key in WHERE clause (REQUIRED).
4. For DynamoDB: Use partition key and optionally sort key.

Example (PostgreSQL):
- Input: "SELECT policy_id, amount FROM demoapp.policies LIMIT 5"
- Output: Columns: policy_id, amount | Rows: 5

Example (Cassandra):
- Input: "SELECT * FROM ecommerce.orders WHERE order_id = 123"
- Output: (partition key is required in WHERE clause)""",
    parameters={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "The SQL SELECT query to execute (use schema-qualified table names)"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of rows to return",
                "default": 1000
            }
        },
        "required": ["sql"]
    }
)

EXECUTE_AND_ANALYZE = ToolDefinition(
    name="execute_and_analyze",
    description="""Execute SQL query and perform comprehensive analysis on the complete result set.

This is the PRIMARY tool for analyst mode. Use this instead of execute_sql when:
- User wants insights, patterns, or analysis
- User asks "what stands out" or "any trends"
- User wants data-driven recommendations

This tool:
1. Executes the SQL query (fetches up to 1000 rows by default)
2. Analyzes returned rows (may sample large datasets for efficiency)
3. Detects insights (trends, outliers, concentrations)
4. Computes statistics (mean, median, distributions)
5. Assesses data quality
6. Recommends optimal chart type

Returns pre-computed analysis, not raw data (efficient token usage).

IMPORTANT RULES:
1. Only SELECT queries allowed (same as execute_sql)
2. Analyzes dataset with smart sampling for large results
3. Default limit: 1000 rows, max: 10000 rows
4. Agent can adjust limit based on query needs

Example:
- Input: sql="SELECT customer, SUM(revenue) FROM orders GROUP BY customer ORDER BY 2 DESC", limit=1000
- Output: {
    "row_count": 856,                  // TRUE row count from the DB
    "analyzed_rows": 856,              // analysis ran on EVERY row (Phase 4)
    "rows_ref": "result:s1:abc-123",   // SAVE THIS — see Phase 4 cache tools
    "rows": [...first 20 rows...],     // 20-row preview for narration
    "insights": [...top 3 customers = 67% concentration...],
    "statistics": {...mean: 45000, median: 12000...},
    "quality": {...95% complete, no nulls in key fields...},
    "chart": {...recommended: bar chart, top 10 customers...}
  }

PHASE 4 CRITICAL: For any FOLLOW-UP question about the SAME dataset (filter,
top-N, describe, group, or specific rows you didn't see in the 20-row
preview), call inspect_cached_result(rows_ref, ...) or get_cached_rows(rows_ref, ...).
Do NOT re-run execute_and_analyze or execute_sql — the full result is already
cached server-side and the cache tools see the EXACT data the user is looking at.""",
    parameters={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "The SQL SELECT query to execute and analyze"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum rows to fetch and analyze (default: 1000, max: 10000)",
                "default": 1000
            },
            "question": {
                "type": "string",
                "description": (
                    "The user's original natural-language question, "
                    "passed verbatim. The LLM uses this as the anchor "
                    "for business-insight narration — without it the "
                    "narrative generator writes generic stat descriptions. "
                    "REQUIRED: always pass the user's question as asked."
                ),
            }
        },
        "required": ["sql", "question"]
    }
)

GET_SAMPLE_DATA = ToolDefinition(
    name="get_sample_data",
    description="""Get sample rows from a table to understand data format and values.
Use this to see what kind of data is in a table before writing queries.
Helps understand column value formats, data quality, and typical values.

IMPORTANT: Use the schema-qualified table name from search_tables or get_table_schema.

Example (PostgreSQL):
- Input: table_name="demoapp.policies", limit=3
- Output:
  Sample data from 'demoapp.policies' (3 rows):
  | policy_id | holder_name | amount   | status  |
  | 1         | John Doe    | 50000.00 | active  |
  ...

Example (Cassandra):
- Input: table_name="ecommerce.orders", limit=3
- Note: For Cassandra, this may require partition key filtering.""",
    parameters={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Schema-qualified table name (e.g., 'schema.table' or 'keyspace.table')"
            },
            "limit": {
                "type": "integer",
                "description": "Number of sample rows to return",
                "default": 5
            }
        },
        "required": ["table_name"]
    }
)


# =============================================================================
# CONVERSATION TOOLS - For multi-turn conversation support
# =============================================================================

GET_PREVIOUS_RESULT = ToolDefinition(
    name="get_previous_result",
    description="""Retrieve result data from a previous query in this conversation.

Use this when:
- User asks to "break down the previous result"
- User says "filter that data" or "from those results"
- User wants to analyze or transform prior query output
- User references "the data" or "those numbers"
- User asks follow-up questions about previous query results

Returns columns, row count, and sample rows (up to 10) from the cached result.

Important: This only works within the same conversation. Results are cached
for the last 10 queries, with 100 rows each.

Example:
- Input: query_reference="last"
- Output: {columns: [...], row_count: 150, sample_rows: [...], sql_used: "SELECT ..."}""",
    parameters={
        "type": "object",
        "properties": {
            "query_reference": {
                "type": "string",
                "description": "'last' or 'previous' for most recent query, or specific query_id",
                "default": "last",
            }
        },
        "required": [],
    },
)


# =============================================================================
# Phase 4.2 — drill into a cached query result without re-executing the SQL
# =============================================================================

GET_CACHED_ROWS = ToolDefinition(
    name="get_cached_rows",
    description="""Fetch a slice of rows from a previously-executed query's full
result set. Use after ``execute_and_analyze`` returns a ``rows_ref`` to look at
specific rows by position.

When to use:
- The user asks "show me rows 100-110" or "what does the 50th row look like"
- You need to quote concrete column values for a few rows in your narrative
- You want to inspect rows the 20-row preview didn't include

Limit is hard-capped at 50 rows per call so the result stays inside the
context budget. For more rows, page with ``offset``.

Example:
- Input: rows_ref="result:s1:abc-123", offset=0, limit=20
- Output: {rows: [...], total_row_count: 9147, columns: [...], has_more: true}""",
    parameters={
        "type": "object",
        "properties": {
            "rows_ref": {
                "type": "string",
                "description": "The rows_ref handle returned by execute_and_analyze",
            },
            "offset": {
                "type": "integer",
                "description": "Row index to start from (0-based)",
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Rows to fetch (max 50)",
                "default": 20,
            },
        },
        "required": ["rows_ref"],
    },
)


INSPECT_CACHED_RESULT = ToolDefinition(
    name="inspect_cached_result",
    description="""Run a structured analytical operation over a cached query
result. Lets you drill into the FULL dataset (not just the 20-row preview)
without re-executing the SQL or pulling all rows into context.

Use when the user wants to investigate a specific aspect of the data they
just got — filter, sort, summarise, or describe a column.

Operations:
  - "filter":         {column, op (eq|ne|gt|gte|lt|lte|in|contains), value}
                      Returns matched_row_count + 10-row sample.
  - "top_n":          {column, n (≤20), direction (asc|desc)}
                      Returns the N highest/lowest rows by that column.
  - "describe":       {column}
                      Numeric stats for one column: count, min, max,
                      mean, median, stdev, p25, p75.
  - "group_summary":  {group_by (column or list), agg_column, agg_fn
                      (count|sum|avg|min|max)}
                      Returns up to 50 group rows with the aggregate value.
  - "count_distinct": {column, top (≤20)}
                      Distinct-value count + top-N values by frequency.

When to use vs. execute_sql: prefer this. It's free (no DB call), it sees the
EXACT rows the user is looking at, and cancellation/timeout don't matter.

Example:
- "Tell me about Indiana": inspect_cached_result(rows_ref, "filter",
  {"column": "state", "op": "eq", "value": "IN"})
- "Top 5 outliers": inspect_cached_result(rows_ref, "top_n",
  {"column": "risk_score", "n": 5, "direction": "desc"})""",
    parameters={
        "type": "object",
        "properties": {
            "rows_ref": {
                "type": "string",
                "description": "The rows_ref handle returned by execute_and_analyze",
            },
            "operation": {
                "type": "string",
                "description": "filter | top_n | describe | group_summary | count_distinct",
                "enum": [
                    "filter",
                    "top_n",
                    "describe",
                    "group_summary",
                    "count_distinct",
                ],
            },
            "params": {
                "type": "object",
                "description": "Operation-specific parameters (see tool description)",
            },
        },
        "required": ["rows_ref", "operation"],
    },
)


# =============================================================================
# ALL TOOLS - For easy iteration
# =============================================================================

ALL_TOOLS = [
    SEARCH_TABLES,
    GET_TABLE_SCHEMA,
    LOOKUP_BUSINESS_TERM,
    FIND_SIMILAR_QUERIES,
    EXECUTE_SQL,
    GET_SAMPLE_DATA,
    GET_PREVIOUS_RESULT,
    GET_CACHED_ROWS,
    INSPECT_CACHED_RESULT,
]


def get_tool_by_name(name: str) -> ToolDefinition:
    """Get a tool definition by name."""
    for tool in ALL_TOOLS:
        if tool.name == name:
            return tool
    raise ValueError(f"Unknown tool: {name}")
