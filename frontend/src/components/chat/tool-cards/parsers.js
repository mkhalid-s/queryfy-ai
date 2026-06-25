/**
 * Tool-result parsers — convert the string payloads ToolRegistry emits
 * into structured shapes the typed cards can render.
 *
 * Closes Tier A9 of the 2026-05-09 audit rollout. Source: Reviewer D move B.
 *
 * Each parser:
 *   - takes the raw result text (`step.content` from the SSE event)
 *   - returns a structured object, or `null` if it can't parse
 *
 * Cards check for `null` and fall back to a generic display, so a
 * future backend change to the result format degrades gracefully
 * instead of crashing the timeline.
 */

/**
 * Pull table names out of `search_tables` formatted output.
 *
 * Backend format (backend/app/services/tools/schema_tools.py:90-118):
 *   Tables matching 'X':
 *
 *   IMPORTANT: ...
 *
 *     - demoapp.customers
 *       Columns: id, name, email
 *     - demoapp.orders
 *       ...
 *
 * @returns {{tables: Array<{name: string, columns: string[]}>}, totalRaw: number}|null
 */
export function parseSearchTablesResult(text) {
  if (!text || typeof text !== 'string') return null
  if (!text.includes('Tables matching') && !text.includes('No tables found')) return null

  // Each table block starts with "  - <qualified_name>" — match the
  // bullet line and capture the name; subsequent indented lines
  // (Columns:, Partition Keys:, etc.) are picked up by lookahead.
  const tableLineRe = /^\s+-\s+([^\s][^\n]*?)\s*$/gm
  const tables = []
  let m
  while ((m = tableLineRe.exec(text)) !== null) {
    const name = m[1].trim()
    if (!name) continue
    // Find the immediate Columns: line after this match (if any).
    const after = text.slice(m.index + m[0].length)
    const colMatch = after.match(/^\s+Columns:\s*([^\n]+)/m)
    const columns = colMatch
      ? colMatch[1].split(',').map((c) => c.trim()).filter(Boolean)
      : []
    tables.push({ name, columns })
  }
  if (tables.length === 0 && text.includes('No tables found')) {
    return { tables: [], empty: true }
  }
  return { tables, empty: tables.length === 0 }
}

/**
 * Parse `get_table_schema` result for table-name + column-count.
 *
 * Backend emits two different shapes:
 *   1. Tool result (`schema_tools.py:get_table_schema`):
 *        Schema for 'demoapp.customers':
 *        Use this name in queries: demoapp.customers
 *        Columns:
 *          - id (integer)
 *          - name (text)
 *   2. Schema-context blob for SQL generation (`vector_db.py:574,655`):
 *        TABLE: customers (schema: demoapp)
 *        COLLECTION: users         # MongoDB path
 *
 * Match either so the same parser works for tool-result *and* for
 * test fixtures of the schema-context blob (which is what A9's
 * mongo-prefix regression test uses).
 */
export function parseTableSchemaResult(text) {
  if (!text || typeof text !== 'string') return null
  // Tool-result header is the production path; check it first.
  const schemaForMatch = text.match(/^Schema for\s+'?([^'\n]+?)'?:/m)
  // Schema-context-blob header (TABLE:/COLLECTION:) is the fallback.
  const tableMatch = text.match(/^(?:TABLE|COLLECTION):\s*([^\s(]+)/m)
  const columnMatches = text.match(/^\s+-\s+\w+/gm) || []
  const tableName =
    (schemaForMatch && schemaForMatch[1].trim()) ||
    (tableMatch && tableMatch[1]) ||
    null
  if (!tableName && columnMatches.length === 0) return null
  return {
    tableName,
    columnCount: columnMatches.length,
  }
}

/**
 * Parse `lookup_business_term` result — backend emits a multiline
 * "Term: NAME / Definition: ... / SQL: ..." block. We surface name
 * + a short definition snippet.
 */
export function parseBusinessTermResult(text) {
  if (!text || typeof text !== 'string') return null
  // Backend's fallback messages have drifted before. Match a few
  // common shapes so the card surfaces "not found" instead of
  // returning null and falling through to the generic preview.
  const lower = text.toLowerCase()
  if (
    lower.includes('not in the business dictionary') ||
    lower.includes('not be in the business dictionary') ||
    lower.includes('no business term found') ||
    lower.includes('term not found')
  ) {
    return { found: false }
  }
  const termMatch = text.match(/(?:^|\n)\s*Term:\s*([^\n]+)/i)
  const defMatch = text.match(/(?:^|\n)\s*Definition:\s*([^\n]+)/i)
  if (!termMatch && !defMatch) return null
  return {
    found: true,
    term: termMatch ? termMatch[1].trim() : null,
    definition: defMatch ? defMatch[1].trim() : null,
  }
}

/**
 * Parse `execute_sql` / `execute_and_analyze` result.
 * Two cases:
 *   - JSON envelope (newer execute_and_analyze)
 *   - "Rows returned: N" / "Documents returned: N" formatted text
 *
 * @returns {{rowCount: number, hasChart: boolean, hasInsights: boolean,
 *            sampling: boolean, rowsRef: string|null}|null}
 */
export function parseExecuteResult(text) {
  if (!text || typeof text !== 'string') return null

  // Try JSON first
  try {
    const obj = JSON.parse(text)
    if (typeof obj === 'object' && obj !== null) {
      return {
        rowCount: typeof obj.row_count === 'number' ? obj.row_count : 0,
        hasChart: Boolean(obj.chart),
        hasInsights: Array.isArray(obj.insights) && obj.insights.length > 0,
        sampling: Boolean(obj.sampling_used),
        rowsRef: obj.rows_ref || null,
      }
    }
  } catch {
    // not JSON — fall through to text matching
  }

  const m = text.match(/(?:Rows|Documents|Results)\s+returned:\s*(\d+)/i)
  if (m) {
    return {
      rowCount: Number(m[1]),
      hasChart: false,
      hasInsights: false,
      sampling: false,
      rowsRef: null,
    }
  }
  return null
}

/**
 * Parse `get_sample_data` result.
 *
 * Backend emits (`query_tools.py:1943`):
 *   Sample data from 'customers' (3 rows):
 *
 *     - id: 1, 2, 3
 *     - name: Alice, Bob, Carol
 *
 * The quoted table name and the row-count suffix were not in the
 * original regex — that pattern silently returned null in production
 * (P1 caught in A9 deep review). Now matches both the live format
 * and the older bare-name fallback.
 */
export function parseSampleDataResult(text) {
  if (!text || typeof text !== 'string') return null
  // Live format: `Sample data from 'NAME' (N rows):`
  // Fallback: `Sample data from NAME:`
  const headerMatch = text.match(
    /^Sample data from\s+'?([^'\s:()]+)'?(?:\s*\([^)]*\))?\s*:/m
  )
  const sampleLines = text.match(/^\s+-\s+\w+:/gm) || []
  if (!headerMatch && sampleLines.length === 0) {
    if (text.toLowerCase().includes('no data found')) {
      return { table: null, empty: true, sampleColumnCount: 0 }
    }
    return null
  }
  return {
    table: headerMatch ? headerMatch[1] : null,
    empty: false,
    sampleColumnCount: sampleLines.length,
  }
}

/**
 * Tool-name → parser dispatch. Used by ToolCard to pick the right
 * card component and pre-parse the result before render.
 */
export const PARSERS = {
  search_tables: parseSearchTablesResult,
  get_table_schema: parseTableSchemaResult,
  lookup_business_term: parseBusinessTermResult,
  execute_sql: parseExecuteResult,
  execute_and_analyze: parseExecuteResult,
  get_sample_data: parseSampleDataResult,
}

/**
 * Tool-name → display name for the card header.
 */
export const TOOL_DISPLAY_NAMES = {
  search_tables: 'Search tables',
  get_table_schema: 'Get table schema',
  lookup_business_term: 'Look up business term',
  execute_sql: 'Execute query',
  execute_and_analyze: 'Execute & analyze',
  get_sample_data: 'Sample data',
  find_similar_queries: 'Similar queries',
  detect_insights: 'Detect insights',
  analyze_statistics: 'Analyze statistics',
  check_data_quality: 'Check data quality',
  compare_periods: 'Compare periods',
  suggest_followups: 'Suggest follow-ups',
  recommend_chart: 'Recommend chart',
  prepare_chart_data: 'Prepare chart data',
  annotate_chart: 'Annotate chart',
  get_cached_rows: 'Get cached rows',
  inspect_cached_result: 'Inspect cached result',
}
