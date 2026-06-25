# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-01-17

### Added
- **Unified Chat API**: Single `/api/v1/chat` endpoint consolidating all query modes
  - `mode: "standard"` for fast SQL generation (single LLM call)
  - `mode: "analyst"` for complete data analysis with insights
  - SSE streaming with events: thinking, sql_chunk, sql_complete, tool_call, tool_result, done, error
- **AI Data Analyst Mode**: ReAct agent providing insight-rich answers
  - Iterative reasoning loop with tool orchestration (LangGraph + LiteLLM)
  - Automatic chart generation with type recommendation
  - Key findings extraction with confidence scores
  - Full reasoning trace for transparency
  - Multi-turn conversation support with context awareness
- **15 Specialized Tools for Analyst Mode**: Comprehensive tool system
  - **Schema & Discovery (5 tools)**: `search_tables`, `get_table_schema`, `lookup_business_term`, `find_similar_queries`, `get_sample_data`
  - **Execution (2 tools)**: `execute_sql`, `execute_and_analyze`
  - **Analysis (8 tools)**: `detect_insights`, `analyze_statistics`, `check_data_quality`, `compare_periods`, `suggest_followups`, `recommend_chart`, `prepare_chart_data`, `annotate_chart`
- **5 Analysis Engines**: Statistical and pattern detection modules
  - **Insight Detector**: Pattern detection, anomaly detection, trend analysis
  - **Statistics Engine**: Distribution analysis, quartiles, variance & standard deviation
  - **Data Quality**: Completeness assessment, consistency checks, issue detection
  - **Comparisons**: Period-over-period analysis (YoY, MoM, QoQ), growth rates
  - **Chart Intelligence**: Type recommendation, data preparation, annotation
- **Multi-Turn Conversations**: Context-aware follow-up questions
  - Conversation history tracking (last 5 turns)
  - Follow-up detection with pattern matching
  - Conversation turn counter
  - `continue_conversation` parameter in chat API
- **Agent State Management**: Configurable checkpointer backends
  - In-memory checkpointer (default, development)
  - PostgreSQL checkpointer (production, horizontal scaling)
  - Thread-based state persistence
  - Resume capability for follow-up questions
- **Answer Generator Service**: Synthesizes final analyst responses
  - Data pattern analysis
  - Automatic chart type selection
  - Confidence scoring based on data quality
- **Pre-commit Configuration**: Code quality enforcement with ruff and mypy
- **MIT License**: Open source license (2026 Mohammad Khalid Shaikh, QueryfyAI)
- **New Favicon Design**: Minimalist data query icon with gradient accents
- **Query History Persistence**: Hybrid hot/cold storage for cross-session re-execution
  - Hot storage: Redis (24h TTL, fast access)
  - Cold storage: PostgreSQL (30+ days retention)
  - Connection-hash verification prevents cross-database execution
  - Automatic PostgreSQL fallback when Redis registry clears
- **Auto Database Migrations**: Alembic migrations run automatically on startup
  - Fails startup if migrations fail (intentional for safety)
  - No manual `alembic upgrade head` required
- **Connection-based History Filtering**: Queries filtered by database connection
  - Each connection has unique hash (SHA256 of connection URL)
  - History shows only queries for current connection
- **DML Operations**: Safe INSERT/UPDATE/DELETE with Preview, Sandbox, and Confirm modes
  - Preview mode shows affected rows without executing
  - Sandbox mode executes in transaction then rolls back
  - Confirm mode with time-limited, single-use tokens
- **Error Classifier**: Intelligent database error classification with adaptive retry strategies
  - Automatic classification of syntax, semantic, timeout, permission errors
  - Strategy-based prompt modification for self-healing SQL
- **Context Studio Panel**: Visual data dictionary management for business glossary and table descriptions
- **OpenTelemetry Distributed Tracing**: Full observability with Jaeger integration
  - Auto-instrumentation for FastAPI, httpx, Redis
  - Manual spans for LLM calls, database queries, agent execution
  - Trace context propagation across services
- **Session Persistence**: localStorage-based session restore with full configuration
- **Live Session Stats**: Real-time session duration and query count tracking in Settings
- **DuckDB/SQLite Connection Pool Support**: Native embedded database connections
- **ClickHouse Support**: OLAP analytics database support
- **Enhanced Chart Analyzer**: Improved data summary detection and edge case handling
- **Cassandra CQL Support**: Full schema extraction with partition/clustering key awareness
- **DynamoDB PartiQL Support**: Schema extraction with GSI/LSI awareness
- **Alembic Database Migrations**: Schema versioning for stateful components
- **Connection Pool Manager**: Multi-database pooling with async/sync bridging
- Collapsible history sidebar with slide-in animation
- Schema-aware dynamic suggestions based on database tables
- Chart customizer component with extended chart types (Gauge, GeoMap, Choropleth)
- Streaming SQL explanation with progressive loading UI
- Conversation context for follow-up queries
- Toast notification system with composable API
- Query options panel (streaming/agentic mode toggles)
- Activity tracking with Pinia store

### Changed
- **UI/UX Redesign**: Modern analyst-focused interface
  - Streaming visualization components for real-time agent progress
  - Tool execution indicators with step-by-step breakdown
  - Key findings cards with severity indicators
  - Data quality score badges
  - Enhanced chart customization options
- **Settings Drawer UX**: Hide configuration forms when session is active, show summary instead
- **Reset Session Flow**: Two-step confirmation with setup wizard prompt after reset
- **Prometheus Metrics**: Added LLM and database query counters
- **Theme Color**: Updated to match new favicon design (#1E293B)
- Renamed "SQL Query" to "Generated Query" in UI
- Improved chart transformers for better visualization detection
- Enhanced MongoDB JSON parsing for nested documents
- Refined design tokens and theme system

### Fixed
- **ResultsExpander Field Binding**: Fixed AIResponseCard using wrong field for results
- **Chart Streaming Fields**: Added missing title, x_label, y_label to streaming response
- **asyncio Import**: Moved from function-level to top-level in chat.py
- **FastAPI OpenTelemetry Instrumentation**: Fixed instrumentor instantiation
- **Schema Extractor Signature**: Fixed `_initialize_schema()` method signature mismatch
- **ECharts Map Rendering**: Prevent 'regions' error by ensuring map data loads before render
- **Session Restore Race Condition**: Config restored before session to prevent watcher override
- MongoDB executor handling of complex nested documents
- Sidebar layout not shifting main content

### Deprecated
- **`/api/v1/query/generate`**: Use `/api/v1/chat` with `mode: "standard"` instead
- **`/api/v1/query/generate/stream`**: Use `/api/v1/chat` with `stream: true` instead
- **`agenticMode` option**: Use `responseMode: "analyst"` instead

### Security
- Enhanced prompt injection detection patterns
- Added session configuration validation on restore

### Accessibility
- Added `aria-label` to QueryInput textarea
- Added `role="dialog"`, `aria-modal`, `aria-labelledby` to SettingsDrawer

### Removed
- Deleted orphaned `AnalystResponseCard.vue` component (997 lines)

## [1.0.0] - 2024-12-14

### Added
- Initial release of QueryfyAI
- Natural Language to SQL conversion engine
- Support for 15+ LLM providers via LiteLLM
- Multi-database support (PostgreSQL, MySQL, SQL Server, Oracle, Snowflake, BigQuery, MongoDB, DuckDB, SQLite)
- Vector-based schema retrieval (RAG) with ChromaDB/Qdrant
- Enterprise OAuth Gateway integration
- Redis-backed session management
- Vue 3 frontend with smart chart visualizations
- Streaming SQL generation with SSE support
- Docker and Kubernetes deployment configurations
- Prometheus/Grafana monitoring stack
- Comprehensive documentation (Runbook, Security Policy, Onboarding Guide)

### Security
- Prompt injection prevention (26+ attack patterns)
- SQL injection protection with AST validation
- Read-only query enforcement
- Session signing with HMAC
- CSRF protection
- Rate limiting per endpoint
