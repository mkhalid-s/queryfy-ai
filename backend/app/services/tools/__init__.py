"""
QueryfyAI - Tool Infrastructure for AI Data Analyst

Tools are wrappers around existing services that:
1. Provide OpenAI-compatible function definitions
2. Handle context injection (session_id, connection_hash, etc.)
3. Format results for LLM consumption (string output)

Available Tools:
- search_tables: Find relevant tables based on a search term
- get_table_schema: Get detailed schema for a specific table
- lookup_business_term: Look up business term definitions
- find_similar_queries: Find similar past queries for few-shot learning
- execute_sql: Execute a SQL query and return results (legacy)
- execute_and_analyze: Execute SQL + full analysis (PRIMARY for analyst mode)
- get_sample_data: Get sample rows from a table

MCP Client:
- Connect to external MCP servers (database-specific, etc.)
- Discover and call tools from remote MCP servers
- Pre-configured templates for common MCP servers (postgres, sqlite, github, etc.)
"""

from app.services.tools.analysis_definitions import (
    ANALYZE_STATISTICS,
    ANNOTATE_CHART,
    CHECK_DATA_QUALITY,
    COMPARE_PERIODS,
    DETECT_INSIGHTS,
    PREPARE_CHART_DATA,
    RECOMMEND_CHART,
    SUGGEST_FOLLOWUPS,
)
from app.services.tools.analysis_tools import (
    analyze_statistics_handler,
    annotate_chart_handler,
    check_data_quality_handler,
    compare_periods_handler,
    detect_insights_handler,
    prepare_chart_data_handler,
    recommend_chart_handler,
    suggest_followups_handler,
)
from app.services.tools.business_tools import lookup_business_term
from app.services.tools.conversation_tools import get_previous_result
from app.services.tools.definitions import (
    EXECUTE_AND_ANALYZE,
    EXECUTE_SQL,
    FIND_SIMILAR_QUERIES,
    GET_CACHED_ROWS,
    GET_PREVIOUS_RESULT,
    GET_SAMPLE_DATA,
    GET_TABLE_SCHEMA,
    INSPECT_CACHED_RESULT,
    LOOKUP_BUSINESS_TERM,
    SEARCH_TABLES,
)
from app.services.tools.mcp_client import (
    MCP_SERVER_TEMPLATES,
    MCPClient,
    MCPConnection,
    MCPServerConfig,
    MCPTool,
    MCPTransportType,
    connect_preset_server,
    get_mcp_client,
)
from app.services.tools.query_tools import (
    execute_and_analyze,
    execute_sql,
    find_similar_queries,
    get_sample_data,
)
from app.services.tools.registry import ToolContext, ToolDefinition, ToolRegistry
from app.services.tools.schema_tools import get_table_schema, search_tables


# Register all tools
def register_all_tools():
    """Register all available tools with the registry."""
    from app.services.tools import (
        analysis_tools,
        business_tools,
        conversation_tools,
        query_tools,
        schema_tools,
    )

    # Schema tools
    ToolRegistry.register(SEARCH_TABLES, schema_tools.search_tables)
    ToolRegistry.register(GET_TABLE_SCHEMA, schema_tools.get_table_schema)

    # Business tools
    ToolRegistry.register(LOOKUP_BUSINESS_TERM, business_tools.lookup_business_term)

    # Query tools
    ToolRegistry.register(FIND_SIMILAR_QUERIES, query_tools.find_similar_queries)
    ToolRegistry.register(EXECUTE_SQL, query_tools.execute_sql)
    ToolRegistry.register(EXECUTE_AND_ANALYZE, query_tools.execute_and_analyze)
    ToolRegistry.register(GET_SAMPLE_DATA, query_tools.get_sample_data)

    # Conversation tools
    ToolRegistry.register(GET_PREVIOUS_RESULT, conversation_tools.get_previous_result)

    # Phase 4.2: drill into cached query results without re-executing the SQL.
    # Imported here to avoid the top-of-file import cycle through registry.py.
    from app.services.tools import cache_inspection_tools
    ToolRegistry.register(GET_CACHED_ROWS, cache_inspection_tools.get_cached_rows)
    ToolRegistry.register(
        INSPECT_CACHED_RESULT, cache_inspection_tools.inspect_cached_result
    )

    # Analysis tools (NEW: Intelligent data analysis)
    ToolRegistry.register(DETECT_INSIGHTS, analysis_tools.detect_insights_handler)
    ToolRegistry.register(ANALYZE_STATISTICS, analysis_tools.analyze_statistics_handler)
    ToolRegistry.register(CHECK_DATA_QUALITY, analysis_tools.check_data_quality_handler)
    ToolRegistry.register(COMPARE_PERIODS, analysis_tools.compare_periods_handler)
    ToolRegistry.register(SUGGEST_FOLLOWUPS, analysis_tools.suggest_followups_handler)
    ToolRegistry.register(RECOMMEND_CHART, analysis_tools.recommend_chart_handler)
    ToolRegistry.register(PREPARE_CHART_DATA, analysis_tools.prepare_chart_data_handler)
    ToolRegistry.register(ANNOTATE_CHART, analysis_tools.annotate_chart_handler)


def validate_tool_registration():
    """
    Validate that all expected tools are properly registered.

    Returns:
        tuple: (success: bool, missing_tools: List[str])
    """
    expected_tools = [
        # Core tools
        "search_tables",
        "get_table_schema",
        "lookup_business_term",
        "find_similar_queries",
        "execute_sql",
        "execute_and_analyze",
        "get_sample_data",
        "get_previous_result",
        # Analysis tools
        "detect_insights",
        "analyze_statistics",
        "check_data_quality",
        "compare_periods",
        "suggest_followups",
        "recommend_chart",
        "prepare_chart_data",
        "annotate_chart",
    ]

    registered_tools = ToolRegistry.get_tool_names()
    missing_tools = [tool for tool in expected_tools if tool not in registered_tools]

    return (len(missing_tools) == 0, missing_tools)


__all__ = [
    # Registry
    "ToolRegistry",
    "ToolDefinition",
    "ToolContext",
    "register_all_tools",
    "validate_tool_registration",
    # Tool definitions
    "SEARCH_TABLES",
    "GET_TABLE_SCHEMA",
    "LOOKUP_BUSINESS_TERM",
    "FIND_SIMILAR_QUERIES",
    "EXECUTE_SQL",
    "EXECUTE_AND_ANALYZE",
    "GET_SAMPLE_DATA",
    "GET_PREVIOUS_RESULT",
    # Analysis tool definitions
    "DETECT_INSIGHTS",
    "ANALYZE_STATISTICS",
    "CHECK_DATA_QUALITY",
    "COMPARE_PERIODS",
    "SUGGEST_FOLLOWUPS",
    "RECOMMEND_CHART",
    "PREPARE_CHART_DATA",
    "ANNOTATE_CHART",
    # Tool functions
    "search_tables",
    "get_table_schema",
    "lookup_business_term",
    "find_similar_queries",
    "execute_sql",
    "execute_and_analyze",
    "get_sample_data",
    "get_previous_result",
    # Analysis tool functions
    "detect_insights_handler",
    "analyze_statistics_handler",
    "check_data_quality_handler",
    "compare_periods_handler",
    "suggest_followups_handler",
    "recommend_chart_handler",
    "prepare_chart_data_handler",
    "annotate_chart_handler",
    # MCP Client
    "MCPClient",
    "MCPConnection",
    "MCPServerConfig",
    "MCPTool",
    "MCPTransportType",
    "get_mcp_client",
    "connect_preset_server",
    "MCP_SERVER_TEMPLATES",
]
