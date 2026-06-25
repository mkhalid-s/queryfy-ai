# Tool Development Guide

**Version:** 1.2.0
**Last Updated:** 2026-01-27

Complete guide for creating custom tools for the ReAct agent, including the ToolDefinition interface, parameter schemas, handler patterns, registration, and best practices.

---

## Table of Contents

- [Overview](#overview)
- [Tool Architecture](#tool-architecture)
- [Creating a Tool](#creating-a-tool)
- [Tool Definition Interface](#tool-definition-interface)
- [Parameter Schemas](#parameter-schemas)
- [Handler Function Patterns](#handler-function-patterns)
- [Tool Registration](#tool-registration)
- [Testing Tools](#testing-tools)
- [Best Practices](#best-practices)
- [Example Tools](#example-tools)

---

## Overview

The ReAct agent uses **tools** to interact with the environment:
- Query database schema
- Execute SQL
- Search business terms
- Analyze data
- Generate insights

Tools are:
- **Self-contained:** Each tool has a clear, single responsibility
- **Composable:** Tools can be chained together
- **LLM-friendly:** Detailed descriptions guide the agent
- **Type-safe:** Pydantic schemas enforce parameter validation

---

## Tool Architecture

### Components

```
┌─────────────────────────────────────────┐
│          ReAct Agent (LangGraph)        │
│  - Decides which tools to call          │
│  - Passes parameters                    │
│  - Processes results                    │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│        Tool Registry (registry.py)      │
│  - Maintains tool catalog               │
│  - Validates parameters                 │
│  - Executes handlers                    │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│      Tool Handlers (query_tools.py)     │
│  - Business logic implementation        │
│  - Return formatted strings             │
│  - Handle errors gracefully             │
└─────────────────────────────────────────┘
```

### File Structure

```
backend/app/services/tools/
├── __init__.py              # Tool exports
├── registry.py              # ToolRegistry, ToolContext
├── definitions.py           # Schema tools, query tools
├── analysis_definitions.py  # Analysis tools
├── query_tools.py           # Query tool handlers
├── analysis_tools.py        # Analysis tool handlers
├── schema_tools.py          # Schema tool handlers
└── business_tools.py        # Business term handlers
```

---

## Creating a Tool

### 5-Step Process

1. **Define the tool** (schema + description)
2. **Implement the handler** (business logic)
3. **Register the tool** (make it available to agent)
4. **Test the tool** (unit + integration tests)
5. **Document usage** (examples + best practices)

---

## Tool Definition Interface

### ToolDefinition Class

Located in `app/services/tools/registry.py`:

```python
from typing import Dict, Any
from pydantic import BaseModel

class ToolDefinition(BaseModel):
    """
    Tool definition compatible with OpenAI, Anthropic, and MCP formats.
    """
    name: str                    # Unique tool identifier (snake_case)
    description: str             # Detailed description (LLM reads this!)
    parameters: Dict[str, Any]   # JSON Schema for parameters
    handler: Optional[Callable] = None  # Handler function (internal)

    class Config:
        arbitrary_types_allowed = True
```

### Example Definition

```python
from app.services.tools.registry import ToolDefinition

MY_TOOL = ToolDefinition(
    name="my_custom_tool",
    description="""Short one-line summary.

Detailed explanation of what this tool does. The LLM reads this to decide
when to use the tool. Be specific about:
- What the tool returns
- When to use it
- What parameters are required
- Any important caveats

Example:
- Input: {"param1": "value"}
- Output: "Result description"
    """,
    parameters={
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "Description of param1"
            },
            "param2": {
                "type": "integer",
                "description": "Description of param2",
                "default": 10
            }
        },
        "required": ["param1"]
    }
)
```

---

## Parameter Schemas

### JSON Schema Format

Parameters follow [JSON Schema](https://json-schema.org/) specification (OpenAI format):

#### Basic Types

```python
parameters = {
    "type": "object",
    "properties": {
        # String
        "name": {
            "type": "string",
            "description": "User's name"
        },

        # Integer
        "age": {
            "type": "integer",
            "description": "User's age",
            "minimum": 0,
            "maximum": 150
        },

        # Number (float)
        "score": {
            "type": "number",
            "description": "Score between 0 and 1",
            "minimum": 0.0,
            "maximum": 1.0
        },

        # Boolean
        "is_active": {
            "type": "boolean",
            "description": "Whether user is active",
            "default": True
        },

        # Array
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of tags",
            "maxItems": 10
        },

        # Enum
        "status": {
            "type": "string",
            "enum": ["pending", "active", "completed"],
            "description": "Current status"
        }
    },
    "required": ["name", "age"]  # Required parameters
}
```

#### Advanced Schemas

**Nested Objects:**
```python
"address": {
    "type": "object",
    "properties": {
        "street": {"type": "string"},
        "city": {"type": "string"},
        "zip": {"type": "string", "pattern": "^[0-9]{5}$"}
    },
    "required": ["city"]
}
```

**Array of Objects:**
```python
"users": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"}
        }
    }
}
```

**OneOf (Union Types):**
```python
"value": {
    "oneOf": [
        {"type": "string"},
        {"type": "number"}
    ],
    "description": "Can be string or number"
}
```

---

## Handler Function Patterns

### Basic Handler

```python
from app.services.tools.registry import ToolContext

async def my_tool_handler(
    context: ToolContext,
    param1: str,
    param2: int = 10
) -> str:
    """
    Handler for my_custom_tool.

    Args:
        context: Tool execution context (db_config, connection_url, etc.)
        param1: Required parameter
        param2: Optional parameter with default

    Returns:
        Formatted string response for the LLM
    """
    try:
        # 1. Validate inputs
        if not param1:
            return "Error: param1 is required"

        # 2. Access context
        db_config = context.db_config
        if not db_config:
            return "Error: No database connection"

        # 3. Perform operation
        result = do_something(param1, param2)

        # 4. Format output for LLM
        return format_output(result)

    except Exception as e:
        # 5. Handle errors gracefully
        logger.error(f"my_tool_handler error: {e}", exc_info=True)
        return f"Error: {str(e)}"
```

### ToolContext Interface

```python
class ToolContext:
    """Context passed to all tool handlers."""
    db_config: Optional[Dict[str, Any]]      # Database configuration
    connection_url: Optional[str]            # Database connection URL
    session_id: Optional[str]                # Current session ID
    llm_config: Optional[Dict[str, Any]]     # LLM configuration
```

---

### Handler Patterns

#### Pattern 1: Query Execution Tool

```python
async def execute_query_handler(
    context: ToolContext,
    sql: str,
    limit: int = 100
) -> str:
    """Execute SQL and return results."""
    import json
    from app.services.database_service import DatabaseService
    from app.models.schemas import DatabaseConfig

    try:
        # Create config from context
        db_config = DatabaseConfig(**context.db_config)

        # Execute query
        result = await DatabaseService.execute_query(
            config=db_config,
            sql=sql,
            limit=limit
        )

        # Return JSON for structured data
        return json.dumps({
            "success": True,
            "columns": result.get("columns", []),
            "rows": result.get("rows", [])[:10],  # Sample
            "row_count": result.get("row_count", 0)
        })

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })
```

#### Pattern 2: Search Tool

```python
async def search_tables_handler(
    context: ToolContext,
    query: str,
    max_results: int = 5
) -> str:
    """Search for relevant tables."""
    from app.services.vector_db import vector_db

    try:
        # Search vector DB
        tables = vector_db.search_tables(
            connection_url=context.connection_url,
            query=query,
            limit=max_results
        )

        if not tables:
            return f"No tables found matching '{query}'"

        # Format as readable text
        output = [f"Found {len(tables)} tables:\n"]
        for i, table in enumerate(tables, 1):
            output.append(f"{i}. {table['name']}")
            output.append(f"   Description: {table.get('description', 'N/A')}")
            output.append(f"   Relevance: {table.get('score', 0):.2f}")
            output.append("")

        return "\n".join(output)

    except Exception as e:
        return f"Error searching tables: {str(e)}"
```

#### Pattern 3: Analysis Tool

```python
async def detect_insights_handler(
    context: ToolContext,
    data: str,
    analysis_types: Optional[List[str]] = None
) -> str:
    """Detect insights in data."""
    import json
    from app.services.analysis_engines import detect_insights

    try:
        # Parse JSON input
        parsed_data = json.loads(data)

        # Run analysis
        insights = detect_insights(parsed_data, analysis_types)

        # Return structured JSON
        return json.dumps({
            "insights": insights,
            "count": len(insights)
        })

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON: {str(e)}",
            "insights": []
        })
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "insights": []
        })
```

---

## Tool Registration

### Step 1: Add Tool Definition

In `definitions.py` or `analysis_definitions.py`:

```python
MY_TOOL = ToolDefinition(
    name="my_custom_tool",
    description="Tool description...",
    parameters={...}
)

# Add to tool list
ALL_TOOLS = [
    SEARCH_TABLES,
    GET_TABLE_SCHEMA,
    MY_TOOL,  # Add here
]
```

### Step 2: Create LangChain Wrapper

In `react_agent.py`, add to `create_langchain_tools()`:

```python
def create_langchain_tools(tool_context: ToolContext) -> List:
    """Create LangChain-compatible tools."""
    from langchain_core.tools import StructuredTool

    tools = []

    # ... existing tools ...

    # my_custom_tool
    async def _my_custom_tool(param1: str, param2: int = 10) -> str:
        """Tool description for LangChain."""
        return await ToolRegistry.execute(
            "my_custom_tool",
            tool_context,
            param1=param1,
            param2=param2
        )

    tools.append(StructuredTool.from_function(
        coroutine=_my_custom_tool,
        name="my_custom_tool",
        description=MY_TOOL.description,
    ))

    return tools
```

### Step 3: Register Handler

In `registry.py`, add to `TOOL_HANDLERS`:

```python
TOOL_HANDLERS = {
    # ... existing handlers ...
    "my_custom_tool": my_tool_handler,
}
```

---

## Testing Tools

### Unit Tests

```python
# tests/test_my_tool.py
import pytest
from app.services.tools.registry import ToolContext, ToolRegistry
from app.services.tools.query_tools import my_tool_handler

@pytest.mark.asyncio
async def test_my_tool_success():
    """Test successful tool execution."""
    context = ToolContext(
        db_config={"db_type": "postgresql", "connection_url": "..."},
        connection_url="...",
        session_id="test-session"
    )

    result = await my_tool_handler(
        context=context,
        param1="test_value",
        param2=20
    )

    assert "expected output" in result

@pytest.mark.asyncio
async def test_my_tool_error_handling():
    """Test tool error handling."""
    context = ToolContext()

    result = await my_tool_handler(
        context=context,
        param1="",  # Invalid input
        param2=10
    )

    assert "Error" in result

@pytest.mark.asyncio
async def test_my_tool_via_registry():
    """Test tool through registry."""
    context = ToolContext(...)

    result = await ToolRegistry.execute(
        "my_custom_tool",
        context,
        param1="test",
        param2=10
    )

    assert result is not None
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_agent_uses_my_tool(test_session):
    """Test agent can call my_custom_tool."""
    from app.services.react_agent import run_react_agent

    result = await run_react_agent(
        question="Use my custom tool to do X",
        llm_config=test_llm_config,
        db_config=test_db_config,
        session_id=test_session
    )

    assert result["success"]
    assert "my_custom_tool" in result["tools_used"]
```

---

## Best Practices

### 1. Write Detailed Descriptions

The LLM reads the description to decide when to use your tool. Be specific:

**❌ Bad:**
```python
description="Searches for data"
```

**✅ Good:**
```python
description="""Search for database tables relevant to a query.
Returns SCHEMA-QUALIFIED table names (e.g., 'schema.table').

IMPORTANT: Always use the full qualified name in SQL queries.

Use this when:
- Need to find tables related to a concept
- User mentions an entity (customer, order, product)
- Building SQL and don't know which tables to use

Example:
- Input: "customer"
- Output: demoapp.customers, demoapp.customer_orders
"""
```

### 2. Return Formatted Strings

LLMs work best with structured text:

**❌ Bad:**
```python
return {"tables": ["table1", "table2"]}  # LLM sees "[object Object]"
```

**✅ Good:**
```python
return """Found 2 tables:
1. demoapp.customers
   - Description: Customer master data
   - Columns: customer_id, name, email

2. demoapp.orders
   - Description: Order transactions
   - Columns: order_id, customer_id, amount
"""
```

### 3. Handle Errors Gracefully

Never raise exceptions - return error messages:

**❌ Bad:**
```python
if not param:
    raise ValueError("param required")
```

**✅ Good:**
```python
if not param:
    return "Error: param is required. Please provide a value."
```

### 4. Keep Tools Focused

Each tool should do **one thing well**:

**❌ Bad:**
```python
async def query_and_analyze_handler(...)
    # Combines execution + analysis (too much!)
```

**✅ Good:**
```python
async def execute_sql_handler(...)
    # Just executes SQL

async def analyze_results_handler(...)
    # Just analyzes data
```

### 5. Use Type Hints

Type hints improve code quality and enable IDE support:

```python
async def my_tool_handler(
    context: ToolContext,
    param1: str,
    param2: Optional[int] = None
) -> str:
    ...
```

### 6. Add Usage Examples

Include examples in the description:

```python
description="""Tool description...

Example:
- Input: {"query": "revenue", "limit": 5}
- Output: Found 3 tables: sales.revenue, finance.revenue_monthly...
"""
```

### 7. Validate Inputs Early

```python
async def my_tool_handler(context: ToolContext, sql: str) -> str:
    # Validate early
    if not sql or not sql.strip():
        return "Error: SQL query is empty"

    if len(sql) > 10000:
        return "Error: SQL too long (max 10,000 characters)"

    # Now safe to proceed
    ...
```

### 8. Log for Debugging

```python
import logging
logger = logging.getLogger(__name__)

async def my_tool_handler(...):
    logger.info(f"my_tool called with param1={param1}")

    try:
        result = do_work()
        logger.debug(f"Result: {result[:100]}...")  # Log sample
        return result
    except Exception as e:
        logger.error(f"my_tool failed: {e}", exc_info=True)
        return f"Error: {str(e)}"
```

### 9. Limit Output Size

Prevent overwhelming the LLM context:

```python
# Limit rows
rows = result.get("rows", [])[:10]  # Max 10 rows

# Truncate long strings
def truncate(s: str, max_len: int = 100) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s

# Limit columns
columns = result.get("columns", [])[:20]  # Max 20 columns
```

### 10. Make Tools Idempotent

Tools should be safe to retry:

```python
# ✅ Idempotent (safe to retry)
async def search_tables_handler(...)
    # Read-only operation

# ❌ Not idempotent (creates side effects)
async def delete_table_handler(...)
    # Modifies state - dangerous!
```

---

## Example Tools

### Example 1: Simple Search Tool

```python
# In definitions.py
SEARCH_CUSTOMERS = ToolDefinition(
    name="search_customers",
    description="""Search for customers by name or email.

Use this when:
- User asks about a specific customer
- Need to find customer ID
- Searching by partial name/email match

Returns: List of matching customers with ID, name, email
    """,
    parameters={
        "type": "object",
        "properties": {
            "search_term": {
                "type": "string",
                "description": "Customer name or email to search for"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return",
                "default": 10
            }
        },
        "required": ["search_term"]
    }
)

# In query_tools.py
async def search_customers_handler(
    context: ToolContext,
    search_term: str,
    limit: int = 10
) -> str:
    """Search for customers."""
    from app.services.database_service import DatabaseService
    from app.models.schemas import DatabaseConfig

    if not context.db_config:
        return "Error: No database connection"

    try:
        db_config = DatabaseConfig(**context.db_config)

        # Build search query
        sql = f"""
        SELECT customer_id, name, email
        FROM customers
        WHERE name ILIKE '%{search_term}%'
           OR email ILIKE '%{search_term}%'
        LIMIT {limit}
        """

        result = await DatabaseService.execute_query(
            config=db_config,
            sql=sql,
            limit=limit
        )

        rows = result.get("rows", [])
        if not rows:
            return f"No customers found matching '{search_term}'"

        # Format output
        output = [f"Found {len(rows)} customers:\n"]
        for row in rows:
            output.append(
                f"ID: {row['customer_id']}, "
                f"Name: {row['name']}, "
                f"Email: {row['email']}"
            )

        return "\n".join(output)

    except Exception as e:
        return f"Error searching customers: {str(e)}"
```

### Example 2: Complex Analysis Tool

```python
# In analysis_definitions.py
COMPARE_SEGMENTS = ToolDefinition(
    name="compare_segments",
    description="""Compare segments (regions, products, etc.) against each other.

Use this when:
- User asks "which region is best?"
- Comparing performance across groups
- Finding top/bottom performers

Returns: Comparison table with rankings and percent differences
    """,
    parameters={
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "JSON string of query results with segment column and value column"
            },
            "segment_column": {
                "type": "string",
                "description": "Column name for segments (e.g., 'region', 'product')"
            },
            "value_column": {
                "type": "string",
                "description": "Column name for values to compare (e.g., 'revenue', 'units')"
            }
        },
        "required": ["data", "segment_column", "value_column"]
    }
)

# In analysis_tools.py
async def compare_segments_handler(
    context: ToolContext,
    data: str,
    segment_column: str,
    value_column: str
) -> str:
    """Compare segments."""
    import json

    try:
        # Parse data
        rows = json.loads(data)

        if not rows:
            return "Error: No data to compare"

        # Aggregate by segment
        segments = {}
        for row in rows:
            segment = row.get(segment_column)
            value = row.get(value_column, 0)

            if segment:
                segments[segment] = segments.get(segment, 0) + value

        # Calculate statistics
        total = sum(segments.values())
        avg = total / len(segments)

        # Rank segments
        ranked = sorted(
            segments.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Format output
        output = [f"Segment Comparison ({len(ranked)} segments):\n"]
        output.append(f"Total: {total:,.2f}")
        output.append(f"Average: {avg:,.2f}\n")

        for i, (segment, value) in enumerate(ranked, 1):
            pct_of_total = (value / total) * 100
            vs_avg = ((value - avg) / avg) * 100

            output.append(
                f"{i}. {segment}: {value:,.2f} "
                f"({pct_of_total:.1f}% of total, "
                f"{vs_avg:+.1f}% vs avg)"
            )

        return "\n".join(output)

    except json.JSONDecodeError:
        return "Error: Invalid JSON data"
    except Exception as e:
        return f"Error comparing segments: {str(e)}"
```

---

## Advanced Topics

### Streaming Tool Output

For long-running tools, stream progress:

```python
async def long_running_tool_handler(
    context: ToolContext,
    param: str
) -> AsyncGenerator[str, None]:
    """Stream tool output."""
    yield "Starting process...\n"

    for i, item in enumerate(large_dataset):
        result = process(item)
        yield f"Processed {i+1}: {result}\n"

    yield "Complete!"
```

### Tool Dependencies

Some tools depend on others:

```python
async def advanced_tool_handler(
    context: ToolContext,
    param: str
) -> str:
    """Tool that uses other tools."""
    from app.services.tools.registry import ToolRegistry

    # Call another tool
    tables = await ToolRegistry.execute(
        "search_tables",
        context,
        query=param
    )

    # Use result
    if "No tables" in tables:
        return "Cannot proceed: no tables found"

    # Continue processing...
    return "Analysis complete"
```

### Caching Tool Results

Cache expensive operations:

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_expensive_data(key: str) -> str:
    """Cached function."""
    return expensive_operation(key)

async def cached_tool_handler(
    context: ToolContext,
    key: str
) -> str:
    """Tool with caching."""
    # Reuses cached result if key seen before
    result = get_expensive_data(key)
    return format_result(result)
```

---

## Related Documentation

- [Agent Reference](./AGENT_REFERENCE.md) - API reference and troubleshooting
- [Analysis Tools Guide](./ANALYSIS_TOOLS_GUIDE.md) - Built-in analysis tools

---

## Tool Development Checklist

- [ ] Tool definition with clear name and description
- [ ] JSON Schema parameters with validation
- [ ] Handler function with type hints
- [ ] Error handling (no exceptions raised)
- [ ] Output formatting (structured text)
- [ ] Unit tests (success + error cases)
- [ ] Integration test (agent can use tool)
- [ ] Documentation (usage examples)
- [ ] Logging for debugging
- [ ] Performance optimization (caching, limits)

---

## Version History

- v1.2.0 (2026-01-27): Added advanced patterns, streaming tools
- v1.1.0 (2026-01-20): Added analysis tool examples
- v1.0.0 (2026-01-15): Initial tool development guide
