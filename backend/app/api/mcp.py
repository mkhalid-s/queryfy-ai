"""
MCP (Model Context Protocol) server endpoint.

Closes Tier A8 of the 2026-05-09 audit rollout. Source: Reviewer B move 1
+ Reviewer H move 3 + Reviewer I — three independent reviewers converged
on "ship an MCP server" as the highest-leverage strategic move. With the
existing REST/SSE API kept untouched, this endpoint reframes QueryfyAI
from "another NL2SQL UI" into "a governed-DB MCP server with NoSQL +
OAuth-gateway support" — the category that *isn't* dissolving in mid-2026.

Exposes the existing tools (no rewrites) via the MCP JSON-RPC 2.0
protocol, so QueryfyAI becomes consumable by any MCP-aware client:
Claude (Desktop & API), ChatGPT Apps, Cursor, Windsurf, Vercel AI SDK,
OpenAI Agents SDK, External Platform Agents.

Transport: Streamable HTTP (MCP protocol 2025-06-18). One POST endpoint
accepts JSON-RPC requests and returns JSON responses. The simpler
non-streaming subset is sufficient for tool calls; streaming is a
follow-up if a client requires it for long-running tools.

Auth: session-based. Clients pass ``X-Session-Id`` header. Session must
exist (was created via POST /api/v1/sessions). The session's
``db_config`` / ``llm_config`` thread through to the ToolContext exactly
as the REST/SSE path does — same tools, same context, different
transport.

Methods supported:
  * ``initialize``    — capabilities exchange
  * ``tools/list``    — return the tool catalog
  * ``tools/call``    — dispatch to ToolRegistry.execute

Method namespaces NOT implemented (return MethodNotFound):
  * ``resources/*``   — no resources exposed (we expose tools only)
  * ``prompts/*``     — no prompt templates
  * ``logging/*``     — out of scope for v0
  * ``sampling/*``    — out of scope (we are the server, not the client)
  * ``notifications/*`` — connection-shape notifications are noise for
                          a non-streaming transport

This endpoint is **additive**. Existing REST/SSE paths are unchanged.
Revert is a route deregistration — no data migrations, no flags.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.version import __version__ as APP_VERSION
from app.middleware.rate_limit import limiter
from app.services.security import ErrorSanitizer
from app.services.session_store import session_store
from app.services.tools.registry import ToolContext, ToolRegistry

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Tool-exposure allowlist (MCP_EXPOSED_TOOLS)
# ---------------------------------------------------------------------------


def _exposed_tool_names() -> Optional[List[str]]:
    """
    Return the configured ``MCP_EXPOSED_TOOLS`` allowlist, or None if
    no allowlist is set (expose every tool the registry knows about).
    Trims to tools that actually exist in the registry — silently
    dropping a typo'd entry is preferable to crashing the endpoint.
    """
    raw = settings.MCP_EXPOSED_TOOLS
    if raw is None:
        return None
    registry_names = ToolRegistry.get_tool_names()
    filtered = [name for name in raw if name in registry_names]
    if len(filtered) != len(raw):
        dropped = sorted(set(raw) - set(registry_names))
        logger.warning(
            f"MCP_EXPOSED_TOOLS contains {len(dropped)} unknown name(s) "
            f"silently dropped: {dropped}"
        )
    return filtered


def _is_tool_exposed(name: str) -> bool:
    """Check whether the given tool name is exposable via MCP."""
    allowlist = _exposed_tool_names()
    if allowlist is None:
        return name in ToolRegistry.get_tool_names()
    return name in allowlist


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 error codes
# Per https://www.jsonrpc.org/specification#error_object
# ---------------------------------------------------------------------------

JRPC_PARSE_ERROR = -32700
JRPC_INVALID_REQUEST = -32600
JRPC_METHOD_NOT_FOUND = -32601
JRPC_INVALID_PARAMS = -32602
JRPC_INTERNAL_ERROR = -32603

# MCP-specific server error range (-32000 to -32099) per JSON-RPC spec.
MCP_TOOL_EXECUTION_ERROR = -32000


# MCP protocol version we negotiate. Clients with mismatched versions
# get a successful initialize with this string back; they can decide
# whether to proceed. Spec versions are dated; this is the 2025-06-18
# revision (current as of mid-2026 per Reviewer B's competitive scan).
MCP_PROTOCOL_VERSION = "2025-06-18"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jrpc_ok(req_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jrpc_err(req_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _require_session(session_id: Optional[str]) -> dict:
    """
    Resolve a session by id or raise the MCP-appropriate auth error.

    Per the MCP spec the transport layer handles auth — we use FastAPI's
    HTTPException here so the response is a 401, not a JSON-RPC envelope.
    Clients that get a 401 know to refresh credentials before retrying.
    """
    if not session_id:
        raise HTTPException(status_code=401, detail="X-Session-Id header required")
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session not found or expired")
    return session


# ---------------------------------------------------------------------------
# Method dispatch
# ---------------------------------------------------------------------------


async def _handle_initialize(
    req_id: Any, params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    MCP initialize handshake.

    Spec: https://modelcontextprotocol.io/specification — clients send
    their protocol version + capabilities; server responds with the
    version it speaks and the capabilities it offers. Mismatches are
    not fatal; clients decide what to do.

    No auth: per the spec, ``initialize`` is the handshake that
    precedes credential exchange in some flows. Real MCP clients
    (Claude Desktop, Cursor) call ``initialize`` first, before they
    have a session id — so requiring X-Session-Id here breaks
    onboarding.
    """
    client_version = (params or {}).get("protocolVersion", "")
    if client_version and client_version != MCP_PROTOCOL_VERSION:
        logger.info(
            "mcp.initialize: protocol version mismatch (client=%s server=%s — proceeding)",
            client_version,
            MCP_PROTOCOL_VERSION,
        )
    return _jrpc_ok(
        req_id,
        {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                # listChanged=True keeps the contract open: clients
                # are told the catalog MAY change, so they should
                # re-query `tools/list` rather than caching forever.
                # Important for Tier B retrieval refactors that will
                # rename / split / version tools. We do NOT currently
                # emit `notifications/tools/list_changed` server-push
                # events (F51 tracks adding them when streaming
                # transport lands per F27); the `listChanged` capability
                # bit alone is enough to keep well-behaved clients
                # honest about re-fetching on reconnect or after
                # explicit invalidation.
                "tools": {"listChanged": True},
            },
            "serverInfo": {
                "name": "queryfyai-tools",
                "version": APP_VERSION,
            },
        },
    )


async def _handle_tools_list(req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return the MCP-format tool catalog filtered by the
    ``MCP_EXPOSED_TOOLS`` allowlist. The ToolRegistry already knows
    how to emit MCP specs (registry.py:to_mcp_spec); we forward them
    minus anything the operator hasn't explicitly opted in.
    """
    all_specs = ToolRegistry.get_all_specs(format="mcp")
    allowlist = _exposed_tool_names()
    if allowlist is not None:
        all_specs = [spec for spec in all_specs if spec.get("name") in allowlist]
    return _jrpc_ok(req_id, {"tools": all_specs})


async def _handle_tools_call(
    req_id: Any,
    params: Dict[str, Any],
    session: dict,
    session_id: str,
) -> Dict[str, Any]:
    """
    Dispatch the tool call to ``ToolRegistry.execute`` with a
    ToolContext built from the session. Same path the existing
    ReAct agent uses — no separate tool surface, no behaviour drift.
    """
    name = (params or {}).get("name")
    arguments = (params or {}).get("arguments", {}) or {}

    if not name:
        return _jrpc_err(
            req_id, JRPC_INVALID_PARAMS, "tools/call missing required field 'name'"
        )
    if not isinstance(arguments, dict):
        return _jrpc_err(
            req_id, JRPC_INVALID_PARAMS, "tools/call 'arguments' must be an object"
        )

    if not _is_tool_exposed(name):
        # Per JSON-RPC, -32601 is reserved for the *RPC method* not
        # being implemented. A missing tool *within* tools/call is a
        # parameter error (-32602 Invalid params).
        #
        # The error message lists the *exposed* tools (after the
        # MCP_EXPOSED_TOOLS allowlist), not the full registry — so a
        # caller probing for hidden tools sees only the public surface.
        exposed = _exposed_tool_names()
        available = (
            sorted(exposed)
            if exposed is not None
            else sorted(ToolRegistry.get_tool_names())
        )
        return _jrpc_err(
            req_id,
            JRPC_INVALID_PARAMS,
            f"unknown tool: {name!r}. Available: {', '.join(available)}",
        )

    context = ToolContext.from_session(session_id=session_id, session_data=session)

    try:
        result = await ToolRegistry.execute(name, context, **arguments)
    except Exception as e:  # pragma: no cover — registry already catches; belt+braces
        logger.error("mcp.tools_call: registry raised through catch-all", exc_info=True)
        sanitized = ErrorSanitizer.sanitize_error(e)
        return _jrpc_err(
            req_id,
            MCP_TOOL_EXECUTION_ERROR,
            f"tool {name!r} failed: {sanitized}",
        )

    # ToolRegistry.execute returns a string (JSON or plain text).
    # Sniff for tool-level failure so the MCP envelope's isError flag
    # is meaningful to client LLMs — without it they treat a payload
    # that says ``{"success": false}`` as a successful call.
    is_error = _result_is_error(result)

    return _jrpc_ok(
        req_id,
        {
            "content": [
                {"type": "text", "text": result}
            ],
            "isError": is_error,
        },
    )


def _result_is_error(result: str) -> bool:
    """
    Return True if a ToolRegistry.execute string represents a tool-
    level failure that MCP clients should treat as an error.

    Two failure shapes the registry emits today:
      1. ``"Error: ..."`` prefix (registry catch-all, unknown-tool).
      2. JSON envelope with ``"success": false``.

    Either shape sets the MCP ``isError`` flag so LLM clients can
    decide whether to retry / surface the error to the user.
    """
    if not result:
        return False
    if result.startswith("Error:") or result.startswith("Error executing "):
        return True
    # JSON envelope sniff — cheap, bounded, won't mis-fire on a string
    # that happens to contain the substring (we require the parsed
    # object to actually have success=false at the top level).
    if result.lstrip().startswith("{"):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and parsed.get("success") is False:
                return True
        except (json.JSONDecodeError, ValueError):
            pass
    return False


# Methods that touch session state OR enumerate the tool surface.
# ``initialize`` is intentionally open per MCP spec — clients call it
# before credential exchange. ``tools/list`` and ``tools/call`` both
# require a valid session, so an unauthenticated client cannot
# enumerate the catalog without first proving session ownership.
_NEEDS_SESSION = frozenset({"tools/list", "tools/call"})


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def _resolve_session_id(
    x_session_id: Optional[str], authorization: Optional[str]
) -> Optional[str]:
    """
    Accept either ``X-Session-Id`` (project-native) or
    ``Authorization: Bearer <session_id>`` (the standard MCP /
    HTTP-API pattern Claude Desktop, Cursor, and Vercel AI SDK
    expect by default). Either form yields the same session id.
    """
    if x_session_id:
        return x_session_id
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[len("bearer "):].strip() or None
    return None


def _check_gate() -> None:
    """Runtime gate: refuse to serve when MCP_ENDPOINT_ENABLED is False.
    The router is mounted unconditionally as of Tier A.5; this handler
    check enforces the gate per-request against the in-process settings
    singleton.

    Note: pydantic-settings reads env vars at construction time, so
    flipping ``MCP_ENDPOINT_ENABLED`` requires a gunicorn SIGHUP (master
    re-execs and re-imports — ~1s connection blip). Not a hot-reload
    in the strict sense, but no full redeploy is needed.
    """
    if not settings.MCP_ENDPOINT_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="MCP endpoint disabled (set MCP_ENDPOINT_ENABLED=true to enable)",
        )


@router.post("/mcp", tags=["MCP"])
@limiter.limit(settings.RATE_LIMIT_MCP)
async def mcp_endpoint(
    request: Request,
    response: Response,
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-Id"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Optional[Dict[str, Any]]:
    """
    MCP JSON-RPC 2.0 endpoint.

    A single POST that accepts an MCP request envelope and returns the
    matching response envelope. Errors at the transport layer (missing
    session, malformed JSON) return HTTP 4xx; errors at the protocol
    layer (unknown method, invalid params, tool failure) return HTTP
    200 with a JSON-RPC ``error`` member.

    Auth: pass the session id via either ``X-Session-Id`` or
    ``Authorization: Bearer <session_id>``. ``initialize`` and
    ``tools/list`` do not require auth (discovery / handshake);
    ``tools/call`` does.

    Example:
        curl -X POST https://host/api/v1/mcp \\
          -H "Authorization: Bearer <session>" \\
          -H "Content-Type: application/json" \\
          -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
    """
    _check_gate()
    try:
        envelope = await request.json()
    except Exception:
        # JSON-RPC says parse errors return id=null per spec.
        return _jrpc_err(None, JRPC_PARSE_ERROR, "invalid JSON body")

    if not isinstance(envelope, dict):
        return _jrpc_err(None, JRPC_INVALID_REQUEST, "request must be a JSON object")

    req_id = envelope.get("id")
    method = envelope.get("method")
    params = envelope.get("params") or {}

    if envelope.get("jsonrpc") != "2.0":
        return _jrpc_err(
            req_id,
            JRPC_INVALID_REQUEST,
            "missing or invalid 'jsonrpc' (must be '2.0')",
        )
    if not isinstance(method, str) or not method:
        return _jrpc_err(req_id, JRPC_INVALID_REQUEST, "missing or invalid 'method'")

    logger.info(f"mcp.request: method={method} id={req_id}")

    # MCP notifications (no `id` field, `method` starts with
    # ``notifications/``) must NOT receive a JSON-RPC response per the
    # spec. Return 202 Accepted with no body. Currently the only
    # notification we expect is ``notifications/initialized``, sent
    # by the client after a successful ``initialize``.
    if method.startswith("notifications/"):
        response.status_code = 202
        return None

    session_id = _resolve_session_id(x_session_id, authorization)

    # Session resolution — only ``tools/call`` needs the session's
    # db_config / llm_config to build a ToolContext.
    session: Optional[dict] = None
    if method in _NEEDS_SESSION:
        session = _require_session(session_id)

    try:
        if method == "initialize":
            return await _handle_initialize(req_id, params)
        if method == "tools/list":
            return await _handle_tools_list(req_id, params)
        if method == "tools/call":
            assert session is not None  # _require_session enforced
            assert session_id is not None
            return await _handle_tools_call(req_id, params, session, session_id)

        # Unsupported method
        return _jrpc_err(
            req_id, JRPC_METHOD_NOT_FOUND, f"method {method!r} is not implemented"
        )
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover — last-resort safety net
        logger.error("mcp.dispatch: unhandled exception", exc_info=True)
        return _jrpc_err(
            req_id, JRPC_INTERNAL_ERROR, ErrorSanitizer.sanitize_error(e)
        )


@router.get("/mcp/manifest", tags=["MCP"])
@limiter.limit(settings.RATE_LIMIT_MCP)
async def mcp_manifest(
    request: Request,
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-Id"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Static manifest endpoint — server name, version, capabilities, and
    the (filtered) tool catalog in MCP format.

    Convenient for service discovery and human inspection. Equivalent
    to running ``initialize`` + ``tools/list`` over the JSON-RPC endpoint.

    Requires a valid session (X-Session-Id or Authorization: Bearer) so
    an unauthenticated client cannot enumerate the tool surface.
    Filtered by ``MCP_EXPOSED_TOOLS`` if the allowlist is configured.
    """
    _check_gate()
    session_id = _resolve_session_id(x_session_id, authorization)
    _require_session(session_id)

    manifest = ToolRegistry.get_mcp_manifest()
    allowlist = _exposed_tool_names()
    if allowlist is not None and isinstance(manifest, dict) and "tools" in manifest:
        manifest = dict(manifest)
        manifest["tools"] = [
            spec for spec in manifest["tools"] if spec.get("name") in allowlist
        ]
    return manifest
