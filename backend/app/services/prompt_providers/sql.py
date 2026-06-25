"""
QueryfyAI - SQL Prompt Provider

Prompt provider for standard SQL databases (PostgreSQL, MySQL, SQL Server, etc.)
"""

import re
from typing import List

from .base import PromptProvider

# Patterns that indicate a complex query requiring reasoning steps
COMPLEX_QUERY_PATTERNS: List[str] = [
    r"\b(join|combine|merge|link)\b",  # Multi-table operations
    r"\b(compare|versus|vs\.?|difference)\b",  # Comparison queries
    r"\b(trend|growth|change|over time)\b",  # Time-series analysis
    r"\b(top|bottom|rank|best|worst)\s+\d+",  # Ranked results with numbers
    r"\b(group|aggregate|subtotal|breakdown)\b",  # Aggregation queries
    r"\b(ratio|percentage|percent|proportion)\b",  # Calculated metrics
    r"\b(average|sum|count|total)\s+.*(by|per|for each)\b",  # Grouped aggregates
    r"\b(year over year|month over month|yoy|mom)\b",  # Period comparisons
    r"\b(correlation|relationship|impact)\b",  # Analytical queries
]


def is_complex_query(question: str) -> bool:
    """Detect if a question requires complex SQL generation."""
    question_lower = question.lower()
    return any(re.search(pattern, question_lower) for pattern in COMPLEX_QUERY_PATTERNS)


class SQLPromptProvider(PromptProvider):
    """
    Prompt provider for SQL databases.

    Covers: PostgreSQL, MySQL, SQL Server, Oracle, SQLite, DuckDB,
            Snowflake, BigQuery, Redshift, ClickHouse, etc.
    """

    DB_TYPE = "sql"
    QUERY_LANGUAGE = "SQL"

    # Standard prompt for simple queries
    SYSTEM_PROMPT_TEMPLATE = """You are an expert SQL query generator. Convert natural language into SQL queries.

RULES:
1. Generate ONLY ONE query - a single SELECT or WITH (CTE) statement
2. NO INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE operations
3. Use exact table/column names from the schema below
4. Use proper JOINs based on foreign keys
5. Add WHERE/GROUP BY/ORDER BY as needed
6. For "top N" requests, use ORDER BY with LIMIT (or TOP for SQL Server)
7. For temporal queries (time-based filtering):
   - Identify date/timestamp columns from the schema (created_at, updated_at, date, timestamp, etc.)
   - Use database-specific date functions:
     * PostgreSQL: WHERE date_column >= CURRENT_DATE - INTERVAL '30 days'
     * MySQL: WHERE date_column >= DATE_SUB(NOW(), INTERVAL 30 DAY)
     * SQL Server: WHERE date_column >= DATEADD(day, -30, GETDATE())
     * SQLite: WHERE date_column >= date('now', '-30 days')
   - DO NOT use LIMIT alone for "last X days" queries - use proper date filtering
   - Patterns: "last X days/weeks/months", "since date", "between dates", "recent", "this year"

DATABASE: {db_type}

SCHEMA:
{schema}
{few_shot_section}
CONVERSATION HISTORY:
{history}

CRITICAL OUTPUT REQUIREMENTS:
- Return ONLY ONE raw SQL query starting with SELECT or WITH
- NO markdown code blocks (no ```)
- NO explanations or comments before/after the query
- NO multiple queries separated by semicolons
- Just the pure SQL statement, nothing else"""

    # Chain-of-Thought prompt for complex queries
    COT_SYSTEM_PROMPT_TEMPLATE = """You are an expert SQL query generator. Convert natural language into SQL queries.

RULES:
1. Generate ONLY ONE query - a single SELECT or WITH (CTE) statement
2. NO INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE operations
3. Use exact table/column names from the schema below
4. Use proper JOINs based on foreign keys
5. Add WHERE/GROUP BY/ORDER BY as needed
6. For "top N" requests, use ORDER BY with LIMIT (or TOP for SQL Server)
7. For temporal queries (time-based filtering):
   - Identify date/timestamp columns from the schema (created_at, updated_at, date, timestamp, etc.)
   - Use database-specific date functions:
     * PostgreSQL: WHERE date_column >= CURRENT_DATE - INTERVAL '30 days'
     * MySQL: WHERE date_column >= DATE_SUB(NOW(), INTERVAL 30 DAY)
     * SQL Server: WHERE date_column >= DATEADD(day, -30, GETDATE())
     * SQLite: WHERE date_column >= date('now', '-30 days')
   - DO NOT use LIMIT alone for "last X days" queries - use proper date filtering
   - Patterns: "last X days/weeks/months", "since date", "between dates", "recent", "this year"

DATABASE: {db_type}

SCHEMA:
{schema}
{few_shot_section}
CONVERSATION HISTORY:
{history}

THINK STEP BY STEP before writing the query:
1. TABLES: Which tables contain the data needed? Check the schema for relevant tables.
2. COLUMNS: What specific columns should be in SELECT? Include all needed fields.
3. JOINS: How do tables relate? Look for foreign keys (id, _id, _fk patterns).
4. FILTERS: What WHERE conditions apply based on the question?
   - For temporal queries: Identify date columns and use proper date functions
   - DO NOT use LIMIT for time-based filtering
5. AGGREGATION: Is GROUP BY needed? What aggregate functions (COUNT, SUM, AVG)?
6. ORDERING: How should results be sorted? What LIMIT applies (only for result count, not date filtering)?

After reasoning through these steps, write the final SQL query.

CRITICAL OUTPUT REQUIREMENTS:
- Return ONLY ONE raw SQL query starting with SELECT or WITH
- NO markdown code blocks (no ```)
- NO explanations or comments before/after the query
- NO multiple queries separated by semicolons
- Just the pure SQL statement, nothing else"""

    @classmethod
    def get_system_prompt(
        cls, schema: str, history: str, db_type: str = "SQL", **kwargs
    ) -> str:
        """Generate SQL system prompt with optional few-shot examples and CoT for complex queries."""
        # Format few-shot examples if provided
        few_shot_examples = kwargs.get("few_shot_examples", [])
        few_shot_section = ""

        if few_shot_examples:
            few_shot_section = (
                "\nSIMILAR QUERIES FROM THIS DATABASE (use as reference):\n"
            )
            for i, example in enumerate(
                few_shot_examples[:3], 1
            ):  # Limit to 3 examples
                question = example.get("natural_query", "")[:150]
                sql = example.get("sql", "")[:400]
                if question and sql:
                    few_shot_section += (
                        f"Example {i}:\n  Question: {question}\n  SQL: {sql}\n\n"
                    )

        # Determine if we should use Chain-of-Thought for complex queries
        user_question = kwargs.get("question", "")
        use_cot = is_complex_query(user_question) if user_question else False

        # Select appropriate template
        template = (
            cls.COT_SYSTEM_PROMPT_TEMPLATE if use_cot else cls.SYSTEM_PROMPT_TEMPLATE
        )

        return template.format(
            schema=schema,
            history=history or "No previous conversation",
            db_type=db_type.upper(),
            few_shot_section=few_shot_section,
        )

    @classmethod
    def clean_response(cls, response: str) -> str:
        """Clean SQL response from LLM."""
        query = cls._remove_markdown_blocks(response)

        # If doesn't start with SELECT/WITH, try to find it
        query_upper = query.upper().strip()
        if not (query_upper.startswith("SELECT") or query_upper.startswith("WITH")):
            # Try to find SELECT or WITH statement
            with_match = re.search(r"(WITH\s+[\s\S]+?)(?:;|\Z)", query, re.IGNORECASE)
            select_match = re.search(
                r"(SELECT\s+[\s\S]+?)(?:;|\Z)", query, re.IGNORECASE
            )

            if with_match:
                query = with_match.group(1)
            elif select_match:
                query = select_match.group(1)

        # Remove SQL comments
        query = re.sub(r"^--.*?\n", "", query, flags=re.MULTILINE)
        query = query.strip()

        # Remove trailing semicolon (we add it when needed)
        query = query.rstrip(";").strip()

        return query


# Specialized SQL dialects can extend this class
class PostgreSQLPromptProvider(SQLPromptProvider):
    """PostgreSQL-specific prompt provider."""

    DB_TYPE = "postgresql"


class MySQLPromptProvider(SQLPromptProvider):
    """MySQL-specific prompt provider."""

    DB_TYPE = "mysql"


class SQLServerPromptProvider(SQLPromptProvider):
    """SQL Server-specific prompt provider with TOP syntax hints."""

    DB_TYPE = "sqlserver"

    SYSTEM_PROMPT_TEMPLATE = SQLPromptProvider.SYSTEM_PROMPT_TEMPLATE.replace(
        "use ORDER BY with LIMIT (or TOP for SQL Server)",
        "use TOP N with ORDER BY (SQL Server syntax)",
    )


class SnowflakePromptProvider(SQLPromptProvider):
    """Snowflake-specific prompt provider."""

    DB_TYPE = "snowflake"


class BigQueryPromptProvider(SQLPromptProvider):
    """BigQuery-specific prompt provider."""

    DB_TYPE = "bigquery"


class DuckDBPromptProvider(SQLPromptProvider):
    """DuckDB-specific prompt provider."""

    DB_TYPE = "duckdb"


class SQLitePromptProvider(SQLPromptProvider):
    """SQLite-specific prompt provider."""

    DB_TYPE = "sqlite"
