"""
A8 carve-out gate — assert `MCP_ENDPOINT_ENABLED` actually controls
whether the MCP endpoint serves traffic.

Flagged by Reviewer D as a covered-by-eyeball-only gap. The feature
flag was added in commit dcc5464 and the runtime-gate semantics
landed in Tier A.5: as of then the MCP router is *always* mounted,
and the gate is enforced inside the handler (returns 503 when the
flag is False). This makes the flag a runtime kill-switch that
doesn't require a worker restart.

Tested invariants:
  - default `False` => POST /api/v1/mcp returns 503
  - explicit `True` => POST /api/v1/mcp returns a valid JSON-RPC
    response (200 with envelope) for the unauthenticated
    `initialize` method
  - the route is always *present* in app.routes regardless of flag
    state (since the handler does the gating now)
  - pristine Settings() reads False as the default

Pattern: toggle `settings.MCP_ENDPOINT_ENABLED` directly between
tests. No more `importlib.reload(app.main)` needed since the gate
fires at request time, not at module load.
"""

from __future__ import annotations

import pytest

from app.services.tools.registry import ToolRegistry


def _has_route(app, path: str) -> bool:
    """Check if a route exists, handling FastAPI 0.138+ _IncludedRouter wrappers."""
    for r in app.routes:
        if getattr(r, "path", None) == path:
            return True
        # FastAPI 0.138+ wraps include_router() in _IncludedRouter dataclass
        if hasattr(r, "original_router") and hasattr(r, "include_context"):
            prefix = getattr(r.include_context, "prefix", "")
            for sub in r.original_router.routes:
                if prefix + getattr(sub, "path", "") == path:
                    return True
        # Older Starlette Mount-style with .routes and .prefix
        elif hasattr(r, "routes"):
            prefix = getattr(r, "prefix", "")
            for sub in r.routes:
                if prefix + getattr(sub, "path", "") == path:
                    return True
    return False


@pytest.fixture(autouse=True)
def _restore_default_after_test():
    """Tests in this file mutate the singleton settings flag — reset
    after each test so other test files see the .env default."""
    from app.core import config

    original = config.settings.MCP_ENDPOINT_ENABLED
    yield
    config.settings.MCP_ENDPOINT_ENABLED = original


def _make_minimal_app():
    """Build a minimal FastAPI app that mounts just the mcp router.
    Mirrors the pattern in test_a8_mcp_server_smoke.py so the gate
    test doesn't pull in the rate-limit middleware (which needs Redis
    in the full main.py app).
    """
    from fastapi import FastAPI

    from app.api import mcp as mcp_module
    from app.middleware.rate_limit import limiter

    app = FastAPI()
    # slowapi's @limiter.limit decorator needs app.state.limiter to
    # resolve `request.app.state.limiter` at call time.
    app.state.limiter = limiter
    app.include_router(mcp_module.router, prefix="/api/v1")
    return app


# ---------------------------------------------------------------------------
# Route is always mounted (Tier A.5: runtime gate, not import-time gate)
# ---------------------------------------------------------------------------


def test_mcp_route_always_present_regardless_of_flag() -> None:
    """As of Tier A.5 the route is mounted unconditionally; the gate
    is enforced at request time, not at module load."""
    app = _make_minimal_app()
    assert _has_route(app, "/api/v1/mcp")
    assert _has_route(app, "/api/v1/mcp/manifest")


# ---------------------------------------------------------------------------
# Default-off behaviour (handler returns 503)
# ---------------------------------------------------------------------------


def test_mcp_endpoint_returns_503_when_disabled() -> None:
    """When the flag is off, hitting /api/v1/mcp returns 503 with a
    clear 'disabled' detail message — not 200, not 404, not 500."""
    from fastapi.testclient import TestClient

    from app.core import config

    config.settings.MCP_ENDPOINT_ENABLED = False
    app = _make_minimal_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


def test_mcp_manifest_returns_503_when_disabled() -> None:
    """Manifest endpoint also gated at request time."""
    from fastapi.testclient import TestClient

    from app.core import config

    config.settings.MCP_ENDPOINT_ENABLED = False
    app = _make_minimal_app()
    client = TestClient(app)
    resp = client.get("/api/v1/mcp/manifest")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Opt-in behaviour (handler dispatches normally)
# ---------------------------------------------------------------------------


def test_mcp_initialize_returns_200_when_enabled() -> None:
    """With the flag on, `initialize` (which doesn't need a session)
    returns a valid JSON-RPC 2.0 envelope."""
    from fastapi.testclient import TestClient

    from app.core import config

    config.settings.MCP_ENDPOINT_ENABLED = True
    app = _make_minimal_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert "result" in body
    assert body["result"]["protocolVersion"]


# ---------------------------------------------------------------------------
# MCP_EXPOSED_TOOLS allowlist (Window 2)
# ---------------------------------------------------------------------------


def test_tools_list_unfiltered_when_no_allowlist(monkeypatch) -> None:
    """When `MCP_EXPOSED_TOOLS=None`, the catalog reflects the full registry."""
    from app.api import mcp as mcp_module

    monkeypatch.setattr(mcp_module.settings, "MCP_EXPOSED_TOOLS", None)
    exposed = mcp_module._exposed_tool_names()
    assert exposed is None


@pytest.fixture
def _two_fake_tools():
    """Register two deterministic fake tools so the allowlist tests
    don't depend on the host process having imported react_agent.
    """
    from app.services.tools.registry import ToolDefinition

    names = ["_allowlist_smoke_tool_a", "_allowlist_smoke_tool_b"]

    async def _handler(context, **kwargs):
        return "ok"

    for n in names:
        ToolRegistry.register(
            ToolDefinition(
                name=n,
                description=f"smoke tool {n}",
                parameters={"type": "object", "properties": {}},
            ),
            _handler,
        )
    yield names
    for n in names:
        ToolRegistry.unregister(n)


def test_tools_list_filtered_by_allowlist(monkeypatch, _two_fake_tools) -> None:
    """When `MCP_EXPOSED_TOOLS=[...]`, only those tools are exposable."""
    from app.api import mcp as mcp_module

    a, b = _two_fake_tools
    monkeypatch.setattr(mcp_module.settings, "MCP_EXPOSED_TOOLS", [a])
    exposed = mcp_module._exposed_tool_names()
    assert exposed == [a]
    assert mcp_module._is_tool_exposed(a)
    # Tool registered but excluded from the allowlist is filtered out.
    assert not mcp_module._is_tool_exposed(b)


def test_unknown_allowlist_entries_silently_dropped(
    monkeypatch, _two_fake_tools
) -> None:
    """Typo'd allowlist entries log a warning but don't crash the endpoint."""
    from app.api import mcp as mcp_module

    a, _ = _two_fake_tools
    monkeypatch.setattr(
        mcp_module.settings,
        "MCP_EXPOSED_TOOLS",
        [a, "definitely_not_a_real_tool"],
    )
    exposed = mcp_module._exposed_tool_names()
    assert exposed == [a]


# ---------------------------------------------------------------------------
# Defensive: assert the config setting exists with the documented default
# ---------------------------------------------------------------------------


def test_mcp_endpoint_enabled_defaults_to_false() -> None:
    """
    Belt-and-braces: pristine `Settings()` (no env override) must read
    `False` for the new flag. Catches a future PR that flips the
    default without updating the staging-soak workflow.
    """
    from app.core.config import Settings

    fresh = Settings()
    assert fresh.MCP_ENDPOINT_ENABLED is False, (
        "MCP_ENDPOINT_ENABLED default changed from False. Per the A8 carve-out "
        "agreed before umbrella → main merge, this must stay off-by-default "
        "until F34 (rate limiting) lands and a ≥1-week staging soak completes."
    )
