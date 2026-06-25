"""
A8 smoke: MCP server endpoint at /api/v1/mcp.

Asserts the JSON-RPC 2.0 envelope is correct and the three supported
methods (initialize, tools/list, tools/call) behave as specified by the
MCP protocol (2025-06-18 revision).

Mock-only — uses fastapi.testclient + a fake tool registered against
the real ToolRegistry so we can exercise the dispatch path without
spinning up a database or LLM.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.api.mcp import MCP_PROTOCOL_VERSION, router as mcp_router
from app.services.tools.registry import ToolDefinition, ToolRegistry


# ---------------------------------------------------------------------------
# Test fixture: minimal app + fake tool registered for the dispatch test
# ---------------------------------------------------------------------------


_TEST_TOOL_NAME = "_a8_smoke_test_tool"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """
    Build a tiny FastAPI app that mounts only the MCP router so we
    don't pay the startup cost of the full app for unit tests.

    Forces ``MCP_ENDPOINT_ENABLED=True`` AND ``MCP_EXPOSED_TOOLS=None``
    (= expose every tool the registry knows about) for the test scope.
    The Tier A.5 curated-5 default would exclude the dispatch tests'
    fake tools; these tests verify dispatch correctness independently
    of the allowlist (which has its own coverage in
    test_f47_review_consensus_smoke.py).

    Wires ``app.state.limiter`` so the @limiter.limit decorator on
    the mcp_endpoint / mcp_manifest routes can resolve correctly.
    """
    from fastapi import FastAPI

    from app.core import config
    from app.middleware.rate_limit import limiter

    monkeypatch.setattr(config.settings, "MCP_ENDPOINT_ENABLED", True)
    monkeypatch.setattr(config.settings, "MCP_EXPOSED_TOOLS", None)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(mcp_router, prefix="/api/v1")
    return TestClient(app)


@pytest.fixture
def fake_tool() -> None:
    """
    Register a deterministic echo tool against the real ToolRegistry
    so tools/call dispatch can be exercised without real handlers.
    Auto-unregisters in the teardown.
    """
    async def _handler(context, **kwargs):
        return f"echo: {kwargs!r}"

    ToolRegistry.register(
        ToolDefinition(
            name=_TEST_TOOL_NAME,
            description="echo for A8 smoke",
            parameters={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": [],
            },
        ),
        _handler,
    )
    yield
    ToolRegistry.unregister(_TEST_TOOL_NAME)


@pytest.fixture
def fake_session(monkeypatch) -> str:
    """
    Stub the session_store lookup so the endpoint can route through
    _require_session without touching Redis.
    """
    from app.api import mcp as mcp_module

    session_data = {
        "id": "fake-session-id",
        "db_config": {"connection_url": "postgresql://test", "db_type": "postgresql"},
        "llm_config": {"provider": "openai"},
    }

    class _FakeStore:
        def get(self, sid):
            if sid == "fake-session-id":
                return session_data
            return None

    monkeypatch.setattr(mcp_module, "session_store", _FakeStore())
    return "fake-session-id"


# ---------------------------------------------------------------------------
# JSON-RPC envelope
# ---------------------------------------------------------------------------


def test_invalid_json_returns_parse_error(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/mcp",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200  # JSON-RPC errors are HTTP 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] is None
    assert body["error"]["code"] == -32700  # Parse error


def test_non_object_body_returns_invalid_request(client: TestClient) -> None:
    resp = client.post("/api/v1/mcp", json=[1, 2, 3])
    body = resp.json()
    assert body["error"]["code"] == -32600
    assert "must be a JSON object" in body["error"]["message"]


def test_missing_jsonrpc_field_returns_invalid_request(client: TestClient) -> None:
    resp = client.post("/api/v1/mcp", json={"method": "initialize", "id": 1})
    body = resp.json()
    assert body["error"]["code"] == -32600
    assert body["id"] == 1


def test_missing_method_returns_invalid_request(client: TestClient) -> None:
    resp = client.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1})
    body = resp.json()
    assert body["error"]["code"] == -32600
    assert body["id"] == 1


def test_unknown_method_returns_method_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    # tools/list doesn't need a session — but unknown does
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "foo/bar"},
    )
    body = resp.json()
    assert body["error"]["code"] == -32601
    assert "not implemented" in body["error"]["message"]


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


def test_initialize_does_not_require_session(client: TestClient) -> None:
    """Per MCP spec, initialize is part of the handshake — clients
    call it before they have credentials wired. Forcing auth here
    breaks onboarding flows (Claude Desktop / Cursor / Vercel AI SDK).
    """
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "result" in body
    assert body["result"]["protocolVersion"]


def test_initialize_returns_capabilities(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
        },
    )
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert "tools" in result["capabilities"]
    # listChanged=True tells clients the catalog may change and they
    # should re-query rather than caching forever. Critical for Tier B
    # retrieval refactors that will rename / split / version tools.
    assert result["capabilities"]["tools"]["listChanged"] is True
    assert result["serverInfo"]["name"] == "queryfyai-tools"
    assert "version" in result["serverInfo"]


def test_initialize_tolerates_protocol_version_mismatch(
    client: TestClient,
) -> None:
    """Mismatched protocolVersion is informational — server still returns its own."""
    resp = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "1900-01-01"},
        },
    )
    body = resp.json()
    assert body["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


def test_tools_list_requires_session(client: TestClient, fake_tool) -> None:
    """tools/list is now session-gated (Tier A.5 Window 2 — Security
    reviewer + Architect reviewer convergence). An unauthenticated
    client would otherwise be able to enumerate the full tool surface,
    which is reconnaissance fodder for an external attacker."""
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert resp.status_code == 401


def test_tools_list_includes_registered_fake_tool(
    client: TestClient, fake_tool, fake_session: str
) -> None:
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"X-Session-Id": fake_session},
    )
    tool_names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert _TEST_TOOL_NAME in tool_names


def test_tools_list_returns_mcp_spec_shape(
    client: TestClient, fake_tool, fake_session: str
) -> None:
    """Each tool spec must have name, description, inputSchema (MCP shape)."""
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"X-Session-Id": fake_session},
    )
    tools = resp.json()["result"]["tools"]
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t
        # MCP spec requires inputSchema to be a JSON Schema object
        assert isinstance(t["inputSchema"], dict)
        assert t["inputSchema"].get("type") == "object"


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------


def test_tools_call_requires_session(client: TestClient, fake_tool) -> None:
    resp = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": _TEST_TOOL_NAME, "arguments": {}},
        },
    )
    assert resp.status_code == 401


def test_tools_call_missing_name_returns_invalid_params(
    client: TestClient, fake_session: str
) -> None:
    resp = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"arguments": {}},
        },
        headers={"X-Session-Id": fake_session},
    )
    body = resp.json()
    assert body["error"]["code"] == -32602


def test_tools_call_unknown_tool_returns_invalid_params(
    client: TestClient, fake_session: str
) -> None:
    """
    Per JSON-RPC, -32601 is reserved for the *RPC method* itself
    being unimplemented. A missing tool *within* tools/call is a
    parameter error (-32602).
    """
    resp = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "_does_not_exist", "arguments": {}},
        },
        headers={"X-Session-Id": fake_session},
    )
    body = resp.json()
    assert body["error"]["code"] == -32602


def test_tools_call_dispatches_through_registry(
    client: TestClient, fake_session: str, fake_tool
) -> None:
    """
    A successful tools/call returns the MCP tool-result envelope:
    {"content": [{"type": "text", "text": "..."}], "isError": false}
    """
    resp = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {
                "name": _TEST_TOOL_NAME,
                "arguments": {"msg": "hello"},
            },
        },
        headers={"X-Session-Id": fake_session},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 42
    result = body["result"]
    assert result["isError"] is False
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert "hello" in result["content"][0]["text"]


def test_tools_call_arguments_not_object_returns_invalid_params(
    client: TestClient, fake_session: str, fake_tool
) -> None:
    resp = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": _TEST_TOOL_NAME, "arguments": "not-a-dict"},
        },
        headers={"X-Session-Id": fake_session},
    )
    body = resp.json()
    assert body["error"]["code"] == -32602


def test_tools_call_accepts_authorization_bearer_header(
    client: TestClient, fake_session: str, fake_tool
) -> None:
    """
    Standard MCP / HTTP-API pattern: clients pass session id via
    ``Authorization: Bearer <session_id>``. Required for Claude
    Desktop / Cursor / Vercel AI SDK out-of-box compat.
    """
    resp = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": _TEST_TOOL_NAME, "arguments": {"msg": "ok"}},
        },
        headers={"Authorization": f"Bearer {fake_session}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is False


def test_tools_call_sets_is_error_on_error_prefix(
    client: TestClient, fake_session: str
) -> None:
    """
    A registered tool that returns a string starting with "Error:"
    must surface as ``isError: true`` in the MCP envelope so client
    LLMs don't pretend a failure succeeded.
    """
    name = "_a8_error_prefix_tool"

    async def _handler(context, **kwargs):
        return "Error: simulated failure for the smoke test"

    ToolRegistry.register(
        ToolDefinition(
            name=name,
            description="emits an Error: prefixed string",
            parameters={"type": "object", "properties": {}},
        ),
        _handler,
    )
    try:
        resp = client.post(
            "/api/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            },
            headers={"X-Session-Id": fake_session},
        )
        body = resp.json()
        assert body["result"]["isError"] is True
        assert "Error:" in body["result"]["content"][0]["text"]
    finally:
        ToolRegistry.unregister(name)


def test_tools_call_sets_is_error_on_json_success_false(
    client: TestClient, fake_session: str
) -> None:
    """
    A tool that returns a JSON envelope with ``success: false`` must
    also flip isError. This is the common shape ToolRegistry emits
    for handler-level failures.
    """
    name = "_a8_json_failure_tool"

    async def _handler(context, **kwargs):
        return '{"success": false, "error": "bad input"}'

    ToolRegistry.register(
        ToolDefinition(
            name=name,
            description="emits success=false JSON",
            parameters={"type": "object", "properties": {}},
        ),
        _handler,
    )
    try:
        resp = client.post(
            "/api/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            },
            headers={"X-Session-Id": fake_session},
        )
        body = resp.json()
        assert body["result"]["isError"] is True
    finally:
        ToolRegistry.unregister(name)


def test_tools_call_is_error_false_on_success_true(
    client: TestClient, fake_session: str
) -> None:
    """Successful tool returns must keep isError=false."""
    name = "_a8_success_tool"

    async def _handler(context, **kwargs):
        return '{"success": true, "data": [1, 2, 3]}'

    ToolRegistry.register(
        ToolDefinition(
            name=name,
            description="emits success=true JSON",
            parameters={"type": "object", "properties": {}},
        ),
        _handler,
    )
    try:
        resp = client.post(
            "/api/v1/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            },
            headers={"X-Session-Id": fake_session},
        )
        body = resp.json()
        assert body["result"]["isError"] is False
    finally:
        ToolRegistry.unregister(name)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def test_notifications_initialized_returns_202_no_body(client: TestClient) -> None:
    """
    Per MCP spec, ``notifications/initialized`` (and any other
    ``notifications/*``) must NOT receive a JSON-RPC response —
    server returns 202 Accepted with no body. Spec-compliant
    clients send this after a successful initialize.
    """
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert resp.status_code == 202
    # Body should be empty / null — not a JSON-RPC envelope
    assert resp.content in (b"", b"null")


def test_notifications_other_namespaced_also_202(client: TestClient) -> None:
    """Any ``notifications/*`` method should get the same treatment."""
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/cancelled"},
    )
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# /mcp/manifest static endpoint
# ---------------------------------------------------------------------------


def test_manifest_endpoint_requires_session(
    client: TestClient, fake_tool
) -> None:
    """Manifest endpoint is session-gated as of Tier A.5 (same rationale
    as tools/list — don't let an unauth client enumerate the surface)."""
    resp = client.get("/api/v1/mcp/manifest")
    assert resp.status_code == 401


def test_manifest_endpoint_returns_static_catalog(
    client: TestClient, fake_tool, fake_session: str
) -> None:
    """Authenticated discovery — server name, version, capabilities, tools."""
    resp = client.get(
        "/api/v1/mcp/manifest",
        headers={"X-Session-Id": fake_session},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "queryfyai-tools"
    assert "version" in body
    assert body["capabilities"]["tools"] is True
    assert isinstance(body["tools"], list)
    tool_names = {t["name"] for t in body["tools"]}
    assert _TEST_TOOL_NAME in tool_names
