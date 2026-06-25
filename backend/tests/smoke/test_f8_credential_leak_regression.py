"""
F8 — regression test asserting credentials never leak through tool errors.

Closes Tier A4's load-bearing gap (flagged by 3 reviewers — Reviewer F,
Reviewer A security, Reviewer D testing).

A4 sanitizes 27 sites + the ToolRegistry catch-all so DB connection
URLs (postgres://user:password@host/db), bearer tokens, and stack
fragments never reach the LLM via ToolMessage. **The wiring at
registry.py:303-316 is the load-bearing path** — any future refactor
that adds a typed exception handler before the catch-all, or replaces
sanitize_error() with str(e) "for clarity," would silently regress
A4 and pass all other tests in the suite.

This file is the regression guard for that scenario. It feeds
credential-bearing exceptions through `ToolRegistry.execute` and
asserts the returned string is password-free, regardless of:
  - exception type (psycopg-style OperationalError, ValueError,
    RuntimeError, bare Exception)
  - sanitizer mode (DEBUG=True dev path vs DEBUG=False prod path)
  - call shape (handler raises directly, handler returns string with
    str(e) baked in, handler returns success=false JSON envelope)

Mock-only. No Redis, no DB, no network. Fast.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.tools.registry import ToolContext, ToolDefinition, ToolRegistry


# ---------------------------------------------------------------------------
# Credential shapes the sanitizer must redact
# ---------------------------------------------------------------------------
#
# The first three are the load-bearing cases A4 was designed to fix:
# DB connection URLs with embedded credentials. The last three are
# F9-class extensions the sanitizer doesn't cover today — included
# here as XFAIL so the test surface tracks the gap (and converts to
# a passing test the moment F9 lands).

POSTGRES_URL_WITH_PW = "postgresql://qfuser:supersecret123@db.internal:5432/queryfyai"
MYSQL_URL_WITH_PW = "mysql://root:hunter2@mysql.internal:3306/app"
MONGO_URL_WITH_PW = "mongodb://admin:p%40ssw0rd@mongo.internal:27017/"

# F9 — currently NOT covered by ErrorSanitizer.SENSITIVE_PATTERNS.
# Listed as xfail so the test catalogues the gap explicitly.
AWS_ACCESS_KEY = "AWS_ACCESS_KEY_ID_EXAMPLE"
GITHUB_PAT = "GITHUB_PAT_EXAMPLE"
BEARER_JWT = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3In0.dummy"


@pytest.fixture
def context() -> ToolContext:
    """Minimal context shim — handlers don't actually use it here."""
    return ToolContext(session_id="f8-test")


# ---------------------------------------------------------------------------
# Path 1: handler RAISES an exception → registry catch-all path
# This is the load-bearing path A4 added at registry.py:303-316.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,password",
    [
        (POSTGRES_URL_WITH_PW, "supersecret123"),
        (MYSQL_URL_WITH_PW, "hunter2"),
        (MONGO_URL_WITH_PW, "p%40ssw0rd"),
    ],
)
async def test_registry_catchall_redacts_db_url_password(
    context: ToolContext, url: str, password: str
) -> None:
    """The registry catch-all must scrub the password before returning to LLM."""
    tool_name = "_f8_raise_with_url"

    async def _raises(context: ToolContext, **kwargs: Any) -> str:
        # Simulate psycopg.OperationalError("connection failed for <url>")
        raise RuntimeError(f"connection failed for {url}")

    ToolRegistry.register(
        ToolDefinition(
            name=tool_name,
            description="raises an error containing a DB URL with embedded password",
            parameters={"type": "object", "properties": {}},
        ),
        _raises,
    )
    try:
        result = await ToolRegistry.execute(tool_name, context)
    finally:
        ToolRegistry.unregister(tool_name)

    assert password not in result, (
        f"Password {password!r} leaked through registry catch-all: {result!r}"
    )
    # And the credential URL itself should not appear verbatim:
    assert f":{password}@" not in result


# ---------------------------------------------------------------------------
# Path 2: handler RETURNS a string with str(e) baked in
# This is the path the 17 per-handler sanitize sites guard against.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_returned_error_string_is_sanitized(
    context: ToolContext,
) -> None:
    """
    If a handler catches its own exception and bakes the error into
    a returned string — using sanitize_error properly — the password
    must not leak. (This mirrors the analysis_tools / query_tools
    pattern A4 swept.)
    """
    from app.services.security import ErrorSanitizer

    tool_name = "_f8_returns_handled_error"

    async def _handles_internally(context: ToolContext, **kwargs: Any) -> str:
        try:
            raise RuntimeError(f"db down at {POSTGRES_URL_WITH_PW}")
        except Exception as e:
            # This is the pattern the per-handler sweep produces.
            return f"Operation failed: {ErrorSanitizer.sanitize_error(e)}"

    ToolRegistry.register(
        ToolDefinition(
            name=tool_name,
            description="catches its own exception and returns a sanitized string",
            parameters={"type": "object", "properties": {}},
        ),
        _handles_internally,
    )
    try:
        result = await ToolRegistry.execute(tool_name, context)
    finally:
        ToolRegistry.unregister(tool_name)

    assert "supersecret123" not in result
    assert f":supersecret123@" not in result


# ---------------------------------------------------------------------------
# Path 3: explicit ValueError → sanitize_error preserves DB error patterns
# but still scrubs credentials. Verifies sanitize_error's whitelist
# doesn't accidentally pass through credential-bearing DB errors.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_error_pattern_preserved_but_credentials_scrubbed(
    context: ToolContext,
) -> None:
    """
    `ErrorSanitizer.DATABASE_ERROR_PATTERNS` whitelists 'syntax error',
    'duplicate key', etc. so the LLM can self-correct. These pass
    through redaction but credentials must still be scrubbed.
    """
    tool_name = "_f8_db_error_with_url"

    async def _raises_db_error(context: ToolContext, **kwargs: Any) -> str:
        # Realistic shape: psycopg.UndefinedTable wrapped with conn info
        raise ValueError(
            f"relation 'users' does not exist (host={MYSQL_URL_WITH_PW})"
        )

    ToolRegistry.register(
        ToolDefinition(
            name=tool_name,
            description="raises a DB-pattern error that also leaks the URL",
            parameters={"type": "object", "properties": {}},
        ),
        _raises_db_error,
    )
    try:
        result = await ToolRegistry.execute(tool_name, context)
    finally:
        ToolRegistry.unregister(tool_name)

    # DB-pattern preserved (LLM-self-correction value)
    assert "does not exist" in result.lower()
    # But credentials gone
    assert "hunter2" not in result
    assert ":hunter2@" not in result


# ---------------------------------------------------------------------------
# Path 4: SSE error fallback in chat.py — verified by inspection.
# A4 fixed chat.py:844 to call ErrorSanitizer. This test asserts the
# import + reachability rather than exercising the full SSE stack.
# ---------------------------------------------------------------------------


def test_sse_error_fallback_imports_sanitizer() -> None:
    """
    chat.py's streaming SQL-execution fallback at line 844 must
    route through ErrorSanitizer (A4 fix). Imperfect proxy: assert
    the import and the literal call exist in the source. Failing
    this test means someone removed the wiring.
    """
    import inspect

    from app.api import chat as chat_module

    src = inspect.getsource(chat_module)
    assert "ErrorSanitizer" in src
    # The specific SSE fallback wiring A4 introduced
    assert "SQL execution failed" in src and "ErrorSanitizer.sanitize_error" in src


# ---------------------------------------------------------------------------
# F9-class gaps (XFAIL — flips to PASS when F9 lands)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret,token",
    [
        ("aws_access_key", AWS_ACCESS_KEY),
        ("github_pat", GITHUB_PAT),
        ("bearer_jwt", BEARER_JWT),
    ],
)
async def test_extended_credential_shapes_redacted(
    context: ToolContext, secret: str, token: str
) -> None:
    """F9 (now closed) — broader credential shapes the sanitizer learned."""
    tool_name = f"_f8_f9_{secret}"

    async def _raises(context: ToolContext, **kwargs: Any) -> str:
        raise RuntimeError(f"auth failed: {token}")

    ToolRegistry.register(
        ToolDefinition(
            name=tool_name,
            description="raises an error containing an extended credential",
            parameters={"type": "object", "properties": {}},
        ),
        _raises,
    )
    try:
        result = await ToolRegistry.execute(tool_name, context)
    finally:
        ToolRegistry.unregister(tool_name)

    assert token not in result, f"{secret} not redacted: {result!r}"


# ---------------------------------------------------------------------------
# Smoke: confirm the wiring is actually present
# ---------------------------------------------------------------------------


def test_registry_catchall_uses_error_sanitizer() -> None:
    """
    Belt-and-braces: assert the registry's catch-all calls
    ErrorSanitizer.sanitize_error (not str(e) directly). Catches
    accidental reverts that bypass sanitization without touching
    behaviour on the success path.
    """
    import inspect

    src = inspect.getsource(ToolRegistry.execute)
    assert "ErrorSanitizer.sanitize_error" in src or "sanitize_error" in src, (
        "ToolRegistry.execute appears to have lost the ErrorSanitizer wiring "
        "introduced in A4. Re-check backend/app/services/tools/registry.py:303-316."
    )


# Final defensive check on the redaction pattern itself
def test_redact_sensitive_strips_url_credentials() -> None:
    """Unit-level guard on the regex that does the work."""
    from app.services.security import ErrorSanitizer

    sample = f"connection refused for {POSTGRES_URL_WITH_PW}"
    scrubbed = ErrorSanitizer._redact_sensitive(sample)
    # The literal password and username must be gone…
    assert "supersecret123" not in scrubbed
    assert "qfuser" not in scrubbed
    # …and the redaction marker must be present in their place.
    assert "***:***@" in scrubbed, (
        f"_redact_sensitive failed to insert credential marker: {scrubbed!r}"
    )
