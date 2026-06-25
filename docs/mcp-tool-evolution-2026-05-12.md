# MCP Tool Catalog Evolution

**Date:** 2026-05-12
**Status:** Adopted (`listChanged: true` capability flipped in commit landing this doc)

Architectural follow-up from the Pass 2 + Pass 3 12-perspective reviews. The Architect P0 was that `initialize` advertised `"tools": {"listChanged": false}`, freezing the external MCP contract before Tier B retrieval refactors will need to rename / split / version tools.

This doc records the catalog-evolution rules MCP-aware clients can rely on going forward.

## Current state

- **`tools` capability**: `{"listChanged": true}` — clients are told the catalog MAY change between calls.
- **Server-push notifications**: NOT emitted today. The capability bit alone is enough to make well-behaved clients re-query `tools/list` rather than cache forever; full `notifications/tools/list_changed` push is tracked as F51, scheduled with the streaming transport work (F27).
- **Default exposed tools**: 5 curated names — `search_tables`, `get_table_schema`, `execute_and_analyze`, `inspect_cached_result`, `lookup_business_term`. Default at commit `cc1e1fa`; operators override via `MCP_EXPOSED_TOOLS=*` or a custom list.

## Tool-rename policy

When Tier B work renames an existing exposed tool:

1. **Add the new name FIRST.** Both `search_tables` AND `search_tables_v2` exposed in the same `tools/list` response. Update the curated default to include both.
2. **Inside `_handle_tools_call`**, accept the old name and emit a WARN log noting it's deprecated; route to the new handler.
3. **Cycle**: at least one minor version with both names exposed and the old name returning a `deprecated` warning in the response payload.
4. **Remove the old name** in the version after that. By then any client that respects `listChanged: true` has re-queried at least once.

## Tool-removal policy

When Tier B work removes a tool entirely (no rename, no replacement):

1. Mark the tool's spec with `deprecated: true` in `tools/list` for at least one minor version (the field is MCP-spec-allowed, ignored by clients that don't know about it).
2. Inside `_handle_tools_call`, return a `_jrpc_err` with a tool-level error message naming the replacement (or "no replacement") and the removal date.
3. Drop from `MCP_EXPOSED_TOOLS` curated default in the version after that. The tool may still exist in the internal `ToolRegistry` if other agent paths use it — only the MCP surface is shrunk.

## Tool-addition policy

When Tier B work adds a NEW tool:

1. Add to the ToolRegistry as usual.
2. **Do NOT** add to the curated `MCP_EXPOSED_TOOLS` default unless it's intended as part of the external contract. Internal tools (e.g., `prepare_chart_data`, `get_previous_result`) stay non-default.
3. To expose for soak before adding to the default, operators set `MCP_EXPOSED_TOOLS=existing_5_tools,new_tool` per-environment.
4. Once soaked, add to the default in `config.py` in a separate small PR.

## Signature-change policy

When an existing tool's input schema changes incompatibly (required field added, type narrowed, etc.):

This is a **rename event** — treat as the rename-policy above with a `_v2` suffix. Do not silently mutate the schema of an exposed tool. The `listChanged` capability gives clients a heads-up to re-query but does NOT promise schema compatibility within a stable name.

## Operator action when the catalog changes

If an operator sees the curated default change in a deploy:

1. Verify the consumer (Claude Desktop / Cursor / Vercel-AI-SDK / etc.) re-queries `tools/list` on each session start. Most well-behaved clients do.
2. If a downstream LLM prompt hard-codes a tool name, update it.
3. Track the deprecated → removed cycle via release notes and the `deprecated: true` flag on the catalog response.

## Reference

- MCP spec capability section: `tools.listChanged` semantics at <https://spec.modelcontextprotocol.io/specification/server/tools/#capabilities>
- `MCP_EXPOSED_TOOLS` default and validator: `backend/app/core/config.py`
- `tools/list` filter logic: `backend/app/api/mcp.py:_exposed_tool_names`
