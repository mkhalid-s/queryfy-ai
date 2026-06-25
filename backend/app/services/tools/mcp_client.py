"""
QueryfyAI - MCP (Model Context Protocol) Client

Connects to external MCP servers (like database-specific MCP servers)
to enhance schema understanding and data exploration.

Example use cases:
- Connect to a PostgreSQL MCP server for advanced schema introspection
- Connect to a Snowflake MCP server for metadata and lineage
- Connect to a dbt MCP server for model documentation

MCP Specification: https://github.com/modelcontextprotocol/specification

Usage:
    from app.services.tools.mcp_client import MCPClient

    # Connect to a database MCP server
    client = MCPClient()
    await client.connect("postgres-mcp", command=["npx", "postgres-mcp"])

    # List available tools
    tools = await client.list_tools("postgres-mcp")

    # Call a tool
    result = await client.call_tool("postgres-mcp", "get_schema", {"table": "users"})
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.version import __version__ as APP_VERSION

logger = logging.getLogger(__name__)


class MCPTransportType(Enum):
    """
    MCP transport types.

    Currently implemented:
    - STDIO: Subprocess with stdin/stdout (fully supported)

    Future (not yet implemented):
    - SSE: Server-Sent Events over HTTP
    - WEBSOCKET: WebSocket connections
    """
    STDIO = "stdio"


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""
    name: str
    transport: MCPTransportType = MCPTransportType.STDIO
    command: Optional[List[str]] = None  # Command to run for STDIO transport
    env: Dict[str, str] = field(default_factory=dict)
    args: List[str] = field(default_factory=list)


@dataclass
class MCPTool:
    """Represents a tool from an MCP server."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str


class MCPConnection:
    """Manages a connection to a single MCP server."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.process: Optional[asyncio.subprocess.Process] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0
        self._initialized = False
        self._tools: List[MCPTool] = []
        self._server_info: Dict = {}

    async def connect(self) -> bool:
        """Establish connection to the MCP server."""
        try:
            if self.config.transport == MCPTransportType.STDIO:
                return await self._connect_stdio()
            else:
                logger.error(f"Unsupported transport: {self.config.transport}")
                return False
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {self.config.name}: {e}")
            return False

    async def _connect_stdio(self) -> bool:
        """Connect via STDIO (subprocess)."""
        if not self.config.command:
            logger.error("No command specified for STDIO transport")
            return False

        try:
            # Start the subprocess
            self.process = await asyncio.create_subprocess_exec(
                *self.config.command,
                *self.config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **self.config.env}
            )

            if self.process.stdout is None or self.process.stdin is None:
                logger.error("Failed to create process pipes")
                return False

            self.reader = self.process.stdout
            self.writer = self.process.stdin

            # Initialize the connection
            return await self._initialize()

        except FileNotFoundError:
            logger.error(f"Command not found: {self.config.command[0]}")
            return False
        except Exception as e:
            logger.error(f"STDIO connection error: {e}")
            return False

    async def _initialize(self) -> bool:
        """Send MCP initialize request."""
        response = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "queryfyai",
                "version": APP_VERSION
            }
        })

        if response and "result" in response:
            self._server_info = response["result"]
            self._initialized = True

            # Send initialized notification
            await self._send_notification("initialized", {})

            # Fetch available tools
            await self._fetch_tools()

            logger.info(f"Connected to MCP server: {self.config.name}")
            return True

        return False

    async def _fetch_tools(self):
        """Fetch available tools from the server."""
        response = await self._send_request("tools/list", {})

        if response and "result" in response:
            tools_data = response["result"].get("tools", [])
            self._tools = [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self.config.name
                )
                for t in tools_data
            ]
            logger.info(f"Discovered {len(self._tools)} tools from {self.config.name}")

    async def _send_request(self, method: str, params: Dict) -> Optional[Dict]:
        """Send a JSON-RPC request and wait for response."""
        if not self.writer or not self.reader:
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params
        }

        try:
            # Write request
            self.writer.write((json.dumps(request) + "\n").encode())
            await self.writer.drain()

            # Read response
            line = await asyncio.wait_for(self.reader.readline(), timeout=30.0)
            if line:
                return json.loads(line.decode())

        except asyncio.TimeoutError:
            logger.error(f"Request timeout: {method}")
        except Exception as e:
            logger.error(f"Request error: {e}")

        return None

    async def _send_notification(self, method: str, params: Dict):
        """Send a JSON-RPC notification (no response expected)."""
        if not self.writer:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }

        try:
            self.writer.write((json.dumps(notification) + "\n").encode())
            await self.writer.drain()
        except Exception as e:
            logger.error(f"Notification error: {e}")

    async def call_tool(self, name: str, arguments: Dict) -> Optional[str]:
        """Call a tool on this MCP server."""
        if not self._initialized:
            logger.error(f"Not connected to {self.config.name}")
            return None

        response = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })

        if response and "result" in response:
            content = response["result"].get("content", [])
            # Extract text content
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts)

        if response and "error" in response:
            return f"Error: {response['error'].get('message', 'Unknown error')}"

        return None

    def get_tools(self) -> List[MCPTool]:
        """Get list of available tools."""
        return self._tools

    async def disconnect(self):
        """Disconnect from the MCP server."""
        if self.process:
            self.process.terminate()
            await self.process.wait()
            self.process = None

        self.reader = None
        self.writer = None
        self._initialized = False
        logger.info(f"Disconnected from MCP server: {self.config.name}")


class MCPClient:
    """
    MCP Client Manager.

    Manages connections to multiple MCP servers and provides
    a unified interface for tool discovery and execution.
    """

    def __init__(self) -> None:
        self._connections: Dict[str, MCPConnection] = {}
        self._tool_index: Dict[str, MCPTool] = {}  # tool_name -> MCPTool

    async def connect(
        self,
        name: str,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
        args: Optional[List[str]] = None
    ) -> bool:
        """
        Connect to an MCP server via STDIO transport.

        Args:
            name: Unique name for this connection
            command: Command to run (e.g., ["npx", "-y", "@modelcontextprotocol/server-postgres"])
            env: Environment variables for the subprocess
            args: Additional arguments for the command

        Returns:
            True if connection successful
        """
        if name in self._connections:
            logger.warning(f"Already connected to {name}, disconnecting first")
            await self.disconnect(name)

        config = MCPServerConfig(
            name=name,
            transport=MCPTransportType.STDIO,
            command=command,
            env=env or {},
            args=args or []
        )

        connection = MCPConnection(config)
        success = await connection.connect()

        if success:
            self._connections[name] = connection
            # Index tools for quick lookup
            for tool in connection.get_tools():
                tool_key = f"{name}:{tool.name}"
                self._tool_index[tool_key] = tool

        return success

    async def disconnect(self, name: str):
        """Disconnect from an MCP server."""
        if name in self._connections:
            await self._connections[name].disconnect()
            # Remove from tool index
            self._tool_index = {
                k: v for k, v in self._tool_index.items()
                if not k.startswith(f"{name}:")
            }
            del self._connections[name]

    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for name in list(self._connections.keys()):
            await self.disconnect(name)

    def list_servers(self) -> List[str]:
        """List connected MCP servers."""
        return list(self._connections.keys())

    def list_tools(self, server_name: Optional[str] = None) -> List[MCPTool]:
        """
        List available tools.

        Args:
            server_name: If specified, only list tools from this server

        Returns:
            List of MCPTool objects
        """
        if server_name:
            if server_name not in self._connections:
                return []
            return self._connections[server_name].get_tools()

        # Return all tools
        return list(self._tool_index.values())

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict
    ) -> Optional[str]:
        """
        Call a tool on a specific MCP server.

        Args:
            server_name: Name of the MCP server
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result as string
        """
        if server_name not in self._connections:
            logger.error(f"Not connected to server: {server_name}")
            return None

        return await self._connections[server_name].call_tool(tool_name, arguments)

    def get_tool_specs(self, format: str = "openai") -> List[Dict]:
        """
        Get tool specifications in various formats.

        Args:
            format: "openai", "anthropic", or "mcp"

        Returns:
            List of tool specifications
        """
        specs = []

        for tool in self._tool_index.values():
            if format == "openai":
                specs.append({
                    "type": "function",
                    "function": {
                        "name": f"{tool.server_name}_{tool.name}",
                        "description": f"[{tool.server_name}] {tool.description}",
                        "parameters": tool.input_schema
                    }
                })
            elif format == "anthropic":
                specs.append({
                    "name": f"{tool.server_name}_{tool.name}",
                    "description": f"[{tool.server_name}] {tool.description}",
                    "input_schema": tool.input_schema
                })
            else:  # mcp
                specs.append({
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                    "_server": tool.server_name
                })

        return specs


# Singleton instance
_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    """Get the singleton MCP client instance."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client


# Pre-configured MCP server templates
MCP_SERVER_TEMPLATES = {
    "postgres": {
        "command": ["npx", "-y", "@modelcontextprotocol/server-postgres"],
        "env_required": ["DATABASE_URL"]
    },
    "sqlite": {
        "command": ["npx", "-y", "@modelcontextprotocol/server-sqlite"],
        "args_required": ["db_path"]
    },
    "filesystem": {
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
        "args_required": ["allowed_directories"]
    },
    "github": {
        "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
        "env_required": ["GITHUB_PERSONAL_ACCESS_TOKEN"]
    },
    "memory": {
        "command": ["npx", "-y", "@modelcontextprotocol/server-memory"]
    }
}


async def connect_preset_server(
    preset: str,
    name: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    args: Optional[List[str]] = None
) -> bool:
    """
    Connect to a pre-configured MCP server.

    Args:
        preset: One of the preset names (postgres, sqlite, filesystem, github, memory)
        name: Optional custom name (defaults to preset name)
        env: Environment variables
        args: Additional arguments

    Returns:
        True if connection successful
    """
    if preset not in MCP_SERVER_TEMPLATES:
        logger.error(f"Unknown preset: {preset}. Available: {list(MCP_SERVER_TEMPLATES.keys())}")
        return False

    template = MCP_SERVER_TEMPLATES[preset]
    client = get_mcp_client()

    return await client.connect(
        name=name or preset,
        command=template["command"],
        env=env or {},
        args=args or []
    )
