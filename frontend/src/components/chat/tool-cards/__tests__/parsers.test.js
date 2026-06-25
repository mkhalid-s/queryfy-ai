/**
 * A9 — parser unit tests for typed tool cards.
 *
 * The cards themselves are presentational; the parsers are what can
 * drift if the backend response format changes. Locking the parsers
 * in place here means a future backend formatter change can't
 * silently degrade the typed-card surface to "empty body".
 */

import { describe, expect, it } from 'vitest'
import {
  parseSearchTablesResult,
  parseTableSchemaResult,
  parseBusinessTermResult,
  parseExecuteResult,
  parseSampleDataResult,
  PARSERS,
  TOOL_DISPLAY_NAMES
} from '../parsers.js'

describe('parseSearchTablesResult', () => {
  it('extracts table names with columns from formatted output', () => {
    const text = `Tables matching 'customer':

IMPORTANT: Use the full qualified name in your SQL.

  - demoapp.customers
    Columns: id, name, email, created_at
  - demoapp.customer_orders
    Columns: id, customer_id, total
`
    const parsed = parseSearchTablesResult(text)
    expect(parsed).not.toBeNull()
    expect(parsed.tables).toHaveLength(2)
    expect(parsed.tables[0].name).toBe('demoapp.customers')
    expect(parsed.tables[0].columns).toContain('id')
    expect(parsed.tables[0].columns).toContain('email')
    expect(parsed.empty).toBe(false)
  })

  it('handles the no-tables-found case', () => {
    const text = "No tables found matching 'unicorn'. Try a different search term."
    const parsed = parseSearchTablesResult(text)
    expect(parsed.empty).toBe(true)
    expect(parsed.tables).toHaveLength(0)
  })

  it('returns null for empty or non-matching text', () => {
    expect(parseSearchTablesResult('')).toBeNull()
    expect(parseSearchTablesResult('random output')).toBeNull()
    expect(parseSearchTablesResult(null)).toBeNull()
  })
})

describe('parseTableSchemaResult', () => {
  it("parses the production tool emit ('Schema for \\'<name>\\':')", () => {
    // Actual `get_table_schema` tool emit per schema_tools.py:291 —
    // quoted qualified name in a `Schema for` header. The previous
    // regex matched only the TABLE: schema-context blob and silently
    // returned no name in production traffic. Caught in A9 deep review.
    const text = `Schema for 'demoapp.customers':

Use this name in queries: demoapp.customers

Columns:
  - id (integer)
  - name (text)
  - email (text)
`
    const parsed = parseTableSchemaResult(text)
    expect(parsed.tableName).toBe('demoapp.customers')
    expect(parsed.columnCount).toBe(3)
  })

  it('falls back to TABLE: header from the schema-context blob', () => {
    // Schema-context blob from vector_db.py:574 — used by SQL
    // generation and the recall@k harness fixtures.
    const text = `TABLE: customers (schema: demoapp)
    Columns:
    - id (integer)
    - name (varchar)
    - email (varchar)
`
    const parsed = parseTableSchemaResult(text)
    expect(parsed.tableName).toBe('customers')
    expect(parsed.columnCount).toBe(3)
  })

  it('handles COLLECTION: prefix for MongoDB schema-context blob', () => {
    const text = `COLLECTION: users
    Fields:
    - _id (ObjectId)
    - email (string)
`
    const parsed = parseTableSchemaResult(text)
    expect(parsed.tableName).toBe('users')
    expect(parsed.columnCount).toBe(2)
  })

  it('returns null for empty text', () => {
    expect(parseTableSchemaResult('')).toBeNull()
    expect(parseTableSchemaResult(null)).toBeNull()
  })
})

describe('parseBusinessTermResult', () => {
  it('extracts term + definition', () => {
    const text = `Term: Monthly Active Users
Definition: Users who have logged in within the last 30 days.
SQL: COUNT(DISTINCT user_id) WHERE last_login >= NOW() - INTERVAL '30 days'`
    const parsed = parseBusinessTermResult(text)
    expect(parsed.found).toBe(true)
    expect(parsed.term).toBe('Monthly Active Users')
    expect(parsed.definition).toContain('logged in')
  })

  it('detects the not-in-dictionary case', () => {
    const text = "The term 'foobar' might not be in the business dictionary yet."
    const parsed = parseBusinessTermResult(text)
    expect(parsed.found).toBe(false)
  })

  it('returns null for empty or unrecognised text', () => {
    expect(parseBusinessTermResult('')).toBeNull()
    expect(parseBusinessTermResult('some random output')).toBeNull()
  })
})

describe('parseExecuteResult', () => {
  it('parses a JSON envelope from execute_and_analyze', () => {
    const text = JSON.stringify({
      success: true,
      row_count: 1234,
      insights: [{ title: 'something' }],
      chart: { type: 'bar' },
      sampling_used: false,
      rows_ref: 'result:s1:q1'
    })
    const parsed = parseExecuteResult(text)
    expect(parsed.rowCount).toBe(1234)
    expect(parsed.hasInsights).toBe(true)
    expect(parsed.hasChart).toBe(true)
    expect(parsed.sampling).toBe(false)
    expect(parsed.rowsRef).toBe('result:s1:q1')
  })

  it('parses formatted-text fallback (Rows returned: N)', () => {
    const text = 'Query executed successfully.\nRows returned: 42'
    const parsed = parseExecuteResult(text)
    expect(parsed.rowCount).toBe(42)
    expect(parsed.hasInsights).toBe(false)
    expect(parsed.hasChart).toBe(false)
  })

  it('accepts NoSQL "Documents returned" wording', () => {
    const text = 'Documents returned: 7'
    const parsed = parseExecuteResult(text)
    expect(parsed.rowCount).toBe(7)
  })

  it('detects sampling flag', () => {
    const text = JSON.stringify({ row_count: 9000, sampling_used: { strategy: 'random' } })
    const parsed = parseExecuteResult(text)
    expect(parsed.sampling).toBe(true)
  })

  it('returns null when nothing parseable', () => {
    expect(parseExecuteResult('')).toBeNull()
    expect(parseExecuteResult('some unrelated chatter')).toBeNull()
  })
})

describe('parseSampleDataResult', () => {
  it('parses the live emit with quoted name and (N rows) suffix', () => {
    // Actual `get_sample_data` tool emit per query_tools.py:1943.
    // Previous regex required ":" directly after a non-space-non-colon
    // token, so it failed on this format and silently returned null
    // in production. Caught in A9 deep review.
    const text = `Sample data from 'customers' (3 rows):

  - id: 1, 2, 3
  - email: a@x.com, b@y.com, c@z.com
`
    const parsed = parseSampleDataResult(text)
    expect(parsed.table).toBe('customers')
    expect(parsed.empty).toBe(false)
    expect(parsed.sampleColumnCount).toBe(2)
  })

  it('accepts the older bare-name fallback', () => {
    const text = `Sample data from customers:
  - id: 1, 2, 3
  - email: a@x.com, b@y.com
`
    const parsed = parseSampleDataResult(text)
    expect(parsed.table).toBe('customers')
    expect(parsed.empty).toBe(false)
    expect(parsed.sampleColumnCount).toBe(2)
  })

  it('handles empty-table case', () => {
    const text = 'No data found in table.'
    const parsed = parseSampleDataResult(text)
    expect(parsed.empty).toBe(true)
  })

  it('returns null for unrecognised text', () => {
    expect(parseSampleDataResult('')).toBeNull()
    expect(parseSampleDataResult('whatever')).toBeNull()
  })
})

describe('PARSERS dispatch table', () => {
  it('exposes a parser for every known typed tool', () => {
    expect(PARSERS.search_tables).toBeDefined()
    expect(PARSERS.get_table_schema).toBeDefined()
    expect(PARSERS.lookup_business_term).toBeDefined()
    expect(PARSERS.execute_sql).toBeDefined()
    expect(PARSERS.execute_and_analyze).toBeDefined()
    expect(PARSERS.get_sample_data).toBeDefined()
  })

  it('shares the same parser between execute_sql and execute_and_analyze', () => {
    expect(PARSERS.execute_sql).toBe(PARSERS.execute_and_analyze)
  })
})

describe('TOOL_DISPLAY_NAMES', () => {
  it('covers every typed tool plus the non-typed analyst tools', () => {
    expect(TOOL_DISPLAY_NAMES.search_tables).toBeDefined()
    expect(TOOL_DISPLAY_NAMES.execute_and_analyze).toBeDefined()
    expect(TOOL_DISPLAY_NAMES.detect_insights).toBeDefined()
    expect(TOOL_DISPLAY_NAMES.recommend_chart).toBeDefined()
    expect(TOOL_DISPLAY_NAMES.get_cached_rows).toBeDefined()
    expect(TOOL_DISPLAY_NAMES.inspect_cached_result).toBeDefined()
  })
})
