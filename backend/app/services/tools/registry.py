"""
QueryfyAI - Tool Registry

Centralized tool management system that:
1. Stores tool definitions (OpenAI function calling format)
2. Maps tool names to handler functions
3. Executes tools with proper context injection
4. Handles errors and result formatting
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from app.core.version import __version__ as APP_VERSION
from app.services.security import ErrorSanitizer

logger = logging.getLogger(__name__)


class ToolDefinition(BaseModel):
    """
    OpenAI-compatible tool definition.

    The definition follows the OpenAI function calling schema:
    https://platform.openai.com/docs/guides/function-calling

    Also supports:
    - Anthropic Claude tool use format
    - MCP (Model Context Protocol) format
    """
    name: str
    description: str
    parameters: Dict[str, Any]

    def to_openai_spec(self) -> Dict:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

    def to_anthropic_spec(self) -> Dict:
        """Convert to Anthropic tool use format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters
        }

    def to_mcp_spec(self) -> Dict:
        """
        Convert to MCP (Model Context Protocol) format.

        MCP is an open protocol for connecting AI assistants to
        external data sources and tools.
        https://github.com/modelcontextprotocol/specification
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.parameters.get("properties", {}),
                "required": self.parameters.get("required", [])
            }
        }


@dataclass
class ToolContext:
    """
    Context passed to tool handlers.

    Contains session-specific information needed for tool execution:
    - session_id: Current session ID
    - connection_url: Database connection URL
    - connection_hash: Hashed connection URL for lookups
    - db_config: Full database configuration
    - llm_config: LLM configuration (if needed)
    - tenant_id: Optional tenant ID for multi-tenancy
    """
    session_id: str
    connection_url: Optional[str] = None
    connection_hash: Optional[str] = None
    db_config: Optional[Any] = None
    llm_config: Optional[Any] = None
    tenant_id: Optional[str] = None
    # Phase 3b.2: async executors (BigQuery/Snowflake) call this callable
    # with a dict payload like {"bytes_scanned": N, "rows_read": M,
    # "elapsed_ms": T, "percent": 37.5} and the streaming layer forwards
    # it as a ``query_progress`` SSE event. Defaults to None so non-
    # streaming callers don't need to plumb a no-op.
    progress_emitter: Optional[Any] = None

    @classmethod
    def from_session(cls, session_id: str, session_data: Dict) -> "ToolContext":
        """Create context from session store data."""
        import hashlib

        connection_url = session_data.get("db_config", {}).get("connection_url", "")
        connection_hash = hashlib.sha256(connection_url.encode()).hexdigest()[:16]

        return cls(
            session_id=session_id,
            connection_url=connection_url,
            connection_hash=connection_hash,
            db_config=session_data.get("db_config"),
            llm_config=session_data.get("llm_config"),
            tenant_id=session_data.get("tenant_id"),
        )


class ToolRegistry:
    """
    Centralized tool management.

    Usage:
        # Register a tool
        ToolRegistry.register(SEARCH_TABLES, search_tables_handler)

        # Get all tool specs for LLM
        specs = ToolRegistry.get_all_specs()

        # Execute a tool
        result = await ToolRegistry.execute("search_tables", context, query="customer")
    """

    _tools: Dict[str, tuple[ToolDefinition, Callable]] = {}
    _initialized: bool = False

    @classmethod
    def register(cls, definition: ToolDefinition, handler: Callable):
        """
        Register a tool with its handler function.

        Args:
            definition: Tool definition with name, description, and parameters
            handler: Async function that executes the tool
        """
        cls._tools[definition.name] = (definition, handler)
        logger.debug(f"Registered tool: {definition.name}")

    @classmethod
    def unregister(cls, name: str):
        """Unregister a tool by name."""
        if name in cls._tools:
            del cls._tools[name]
            logger.debug(f"Unregistered tool: {name}")

    @classmethod
    def get_tool(cls, name: str) -> Optional[tuple[ToolDefinition, Callable]]:
        """Get a tool by name."""
        return cls._tools.get(name)

    @classmethod
    def get_definition(cls, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        tool = cls._tools.get(name)
        return tool[0] if tool else None

    @classmethod
    def get_all_specs(cls, format: str = "openai") -> List[Dict]:
        """
        Get all tool specifications for LLM consumption.

        Args:
            format: "openai", "anthropic", or "mcp"

        Returns:
            List of tool specifications in the requested format
        """
        specs = []
        for defn, _ in cls._tools.values():
            if format == "anthropic":
                specs.append(defn.to_anthropic_spec())
            elif format == "mcp":
                specs.append(defn.to_mcp_spec())
            else:
                specs.append(defn.to_openai_spec())
        return specs

    @classmethod
    def get_mcp_manifest(cls) -> Dict:
        """
        Get full MCP server manifest.

        Returns a manifest suitable for MCP server registration.
        """
        return {
            "name": "queryfyai-tools",
            "version": APP_VERSION,
            "description": "QueryfyAI database analysis tools",
            "tools": cls.get_all_specs(format="mcp"),
            "capabilities": {
                "tools": True,
                "resources": False,
                "prompts": False
            }
        }

    @classmethod
    def get_tool_names(cls) -> List[str]:
        """Get list of all registered tool names."""
        return list(cls._tools.keys())

    @classmethod
    async def execute(
        cls,
        name: str,
        context: ToolContext,
        **kwargs
    ) -> str:
        """
        Execute a tool by name with the given arguments.

        Args:
            name: Tool name
            context: Tool execution context
            **kwargs: Tool-specific arguments

        Returns:
            String result from the tool (for LLM consumption)
        """
        if name not in cls._tools:
            error_msg = f"Unknown tool: '{name}'. Available: {', '.join(cls._tools.keys())}"
            logger.error(error_msg)
            return f"Error: {error_msg}"

        _, handler = cls._tools[name]

        try:
            logger.info(f"Executing tool: {name} with args: {kwargs}")
            result = await handler(context=context, **kwargs)

            # Handle result based on type - structured data vs plain text
            JSON_LIMIT = 50000
            if isinstance(result, (dict, list)):
                # Structured data - serialize as JSON
                try:
                    result_str = json.dumps(result)

                    if len(result_str) > JSON_LIMIT:
                        logger.warning(
                            f"Tool {name} JSON result too large: {len(result_str)} chars (limit {JSON_LIMIT})"
                        )
                        return json.dumps({
                            "success": False,
                            "error": "Result too large for processing",
                            "message": f"Analysis output exceeded {JSON_LIMIT // 1000}KB. Try a more specific query or smaller dataset.",
                            "size_chars": len(result_str)
                        })

                    logger.debug(f"Tool {name} returned JSON: {len(result_str)} chars")
                    return result_str

                except (TypeError, ValueError) as e:
                    # Fallback if object isn't JSON-serializable
                    logger.warning(f"Tool {name} returned non-serializable object: {e}")
                    result_str = str(result)
            else:
                # String result — check if it's a JSON string from tools
                # that pre-serialize (execute_and_analyze, execute_sql, etc.)
                result_str = str(result)

                # If the string is valid JSON, apply JSON-aware truncation
                # to avoid slicing mid-escape-sequence and producing invalid JSON
                if result_str.startswith('{') or result_str.startswith('['):
                    try:
                        parsed = json.loads(result_str)
                        # Re-serialize through the JSON path with its 50KB limit
                        result_str = json.dumps(parsed)
                        if len(result_str) > JSON_LIMIT:
                            logger.warning(
                                f"Tool {name} JSON string result too large: {len(result_str)} chars (limit {JSON_LIMIT})"
                            )
                            return json.dumps({
                                "success": False,
                                "error": "Result too large for processing",
                                "message": f"Analysis output exceeded {JSON_LIMIT // 1000}KB. Try a more specific query or smaller dataset.",
                                "size_chars": len(result_str)
                            })
                        logger.debug(f"Tool {name} returned JSON string: {len(result_str)} chars")
                        return result_str
                    except (json.JSONDecodeError, ValueError):
                        pass  # Not valid JSON, fall through to text truncation

            # Plain text truncation
            TEXT_LIMIT = 10000
            if len(result_str) > TEXT_LIMIT:
                result_str = result_str[:TEXT_LIMIT] + "\n... (truncated)"
                logger.debug(f"Tool {name} text truncated to {TEXT_LIMIT} chars")

            return result_str

        except Exception as e:
            # Sanitize before the message goes back to the LLM as a
            # ToolMessage. Raw str(e) can include DB connection URLs
            # with credentials, file paths, stack fragments, and
            # provider hostnames — the LLM can echo any of those to
            # the user despite the SYSTEM_PROMPT voice rule.
            # Internal logs keep the full exception via exc_info=True.
            sanitized = ErrorSanitizer.sanitize_error(e)
            logger.error(
                "Tool %s raised; returning sanitized message to LLM",
                name,
                exc_info=True,
            )
            return f"Error executing {name}: {sanitized}"

    @classmethod
    def reset(cls):
        """Reset the registry (for testing)."""
        cls._tools = {}
        cls._initialized = False

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if tools have been registered."""
        return cls._initialized

    @classmethod
    def mark_initialized(cls):
        """Mark registry as initialized."""
        cls._initialized = True
