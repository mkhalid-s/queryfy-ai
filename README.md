# QueryfyAI

A production-ready Natural Language to SQL query generator with enterprise-grade security, multi-database support, and corporate OAuth gateway integration.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Production Deployment](#production-deployment)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Security](#security)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Features

### Core Functionality
- **Natural Language to SQL**: Convert plain English questions into optimized SQL queries
- **AI Data Analyst Mode**: Get insight-rich answers with SQL, auto-generated charts, key findings, and confidence scores via ReAct agent
  - **15 Specialized Tools**: Schema search, business term lookup, query similarity, sample data, SQL execution with analysis
  - **5 Analysis Engines**: Insight detection, statistical analysis, data quality assessment, period comparison, chart intelligence
  - **Multi-Turn Conversations**: Context-aware follow-up questions with conversation history
  - **Streaming Support**: Real-time agent reasoning and tool execution with Server-Sent Events (SSE)
  - **Intelligent Insights**: Automatic pattern detection, anomalies, trends, and data quality scoring
  - **Chart Intelligence**: Auto-detected chart types with data-driven recommendations
- **Unified Chat API**: Single `/chat` endpoint for all query modes (standard SQL generation or full analyst experience)
- **Multi-Database Support**: PostgreSQL, MySQL, MariaDB, SQL Server, Oracle, Snowflake, BigQuery, Redshift, MongoDB, Cassandra, DynamoDB, DuckDB, SQLite, ClickHouse, Trino, Presto, Athena, Hive, Spark, Databricks (19 databases)
- **Streaming SQL Generation**: Real-time character-by-character SQL streaming with Server-Sent Events (SSE)
- **Query Execution**: Execute generated queries with configurable row limits (up to 1M rows)
- **DML Operations**: Safe INSERT/UPDATE/DELETE with Preview, Sandbox, and Confirm modes
- **Smart Visualizations**: Automatic chart type detection (bar, line, pie, scatter, area, gauge, geo) with customization
- **Excel Export**: Export query results to XLSX spreadsheets
- **SQL Explanation**: Streaming plain-language explanations with progressive rendering
- **Conversation Memory**: Context-aware follow-up questions using conversation history
- **Intelligent Query Generation**: Few-shot learning, Chain-of-Thought reasoning, and self-correction for improved accuracy
- **Self-Healing SQL Agent**: Automatic error classification and adaptive retry strategies
- **Native NoSQL Support**: Direct MongoDB Aggregation Pipeline generation (no SQL translation required)
- **Context Studio**: Visual data dictionary management for business glossary and table descriptions

### Enterprise Features
- **OAuth Gateway Support**: Corporate LLM gateway with automatic token refresh
- **15+ LLM Providers**: OpenAI, Anthropic, Azure, AWS Bedrock, Google Vertex AI, Gemini, Groq, Ollama, Together AI, Mistral, Cohere, DeepSeek, Replicate, and custom endpoints
- **Pluggable Vector Database**: ChromaDB (default), Qdrant, with extensible architecture
- **Session Management**: Redis-backed with automatic in-memory fallback, localStorage persistence
- **Production-Ready**: Docker multi-stage builds, health checks, Prometheus metrics, Kubernetes manifests
- **Database Migrations**: Alembic-based schema migrations for stateful components
- **OpenTelemetry Tracing**: Distributed tracing with Jaeger integration for observability

### Security
- **Prompt Injection Prevention**: Multi-layer defense with 26+ attack pattern detection
- **SQL Injection Protection**: AST-based validation and sanitization
- **Read-Only Enforcement**: Only SELECT/WITH queries allowed
- **Session Locking**: Configuration immutable after first query
- **CSRF Protection**: Token-based request validation
- **Security Headers**: CSP, X-Frame-Options, XSS protection

### User Experience
- **Collapsible History Sidebar**: Slide-in panel for browsing and replaying past queries
- **Schema-Aware Suggestions**: Dynamic query suggestions based on actual database tables
- **Query History**: Track and replay past queries with search and pinning
- **Feedback System**: Rate queries (1-5 stars) for continuous improvement
- **Chart Customizer**: Customize visualization types, colors, and display options
- **Toast Notifications**: Non-blocking feedback for actions and errors
- **Mocha Theme System**: Dark/light themes with smooth transitions
- **Keyboard Shortcuts**: Ctrl+Enter to submit, Escape to clear/close
- **Session Persistence**: Automatic session restore with configuration on page refresh
- **Live Session Stats**: Real-time session duration and query count tracking
- **Context Studio Panel**: Slide-in interface for managing data dictionary entries
- **Adaptive Result Views**: Automatic switching between Table view (SQL) and Document view (NoSQL/JSON)

---

## Architecture

### High-Level Overview

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        Browser["Web Browser"]
    end

    subgraph Frontend["Frontend Container"]
        Nginx["Nginx<br/>:80/:443"]
        Vue["Vue 3 SPA<br/>(Vite Build)"]
    end

    subgraph Backend["Backend Container"]
        Gunicorn["Gunicorn + Uvicorn<br/>:8000"]
        FastAPI["FastAPI Application"]
        subgraph Services["Core Services"]
            LLMSvc["LLM Service"]
            DBSvc["Database Service"]
            SecSvc["Security Service"]
        end
    end

    subgraph Storage["Storage Layer"]
        Redis["Redis<br/>:6379"]
        VectorDB["Vector DB<br/>(ChromaDB)"]
    end

    subgraph External["External Services"]
        LLM["LLM API<br/>(OAuth Gateway)"]
        TargetDB["Target Database"]
    end

    Browser --> Nginx
    Nginx --> Vue
    Nginx -->|"/api/*"| Gunicorn
    Gunicorn --> FastAPI
    FastAPI --> Services
    LLMSvc --> Redis
    LLMSvc --> VectorDB
    LLMSvc --> LLM
    DBSvc --> TargetDB
```

### Component Details

| Component | Technology | Description |
|-----------|------------|-------------|
| Frontend | Vue 3 + Vite + TypeScript | Single-page application with Tailwind CSS |
| Web Server | Nginx | Static file serving, reverse proxy, SSL termination, rate limiting |
| Backend | FastAPI + Gunicorn | ASGI server with 4 Uvicorn workers |
| Session Store | Redis | Session persistence, token caching (optional) |
| Vector DB | ChromaDB | Schema embeddings for RAG-based context retrieval |
| LLM Provider | OAuth Gateway | Enterprise LLM access with automatic token refresh |

### Request Flow

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant B as Backend
    participant V as Vector DB
    participant L as LLM API
    participant D as Target DB

    U->>F: Enter natural language query
    F->>B: POST /api/v1/chat (mode: standard)
    B->>B: Validate input (security checks)
    B->>V: Retrieve relevant schema context
    V-->>B: Schema embeddings
    B->>L: Generate SQL (schema + query + history)
    L-->>B: SQL query (streamed)
    B->>B: Validate SQL (security checks)
    B-->>F: SSE events (sql_chunk, sql_complete)

    U->>F: Click "Execute"
    F->>B: POST /api/v1/query/execute
    B->>B: Verify sql_hash integrity
    B->>D: Execute SQL (read-only)
    D-->>B: Query results
    B-->>F: Results + row_count + has_more
    F-->>U: Display results + chart
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- Redis (optional, falls back to in-memory)

### Development Setup

**Backend:**

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your LLM and database settings

# Run database migrations (if using PostgreSQL for state)
alembic upgrade head

# Run development server
uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Access the application at `http://localhost:5173`

### Try Analyst Mode

To experience the full power of QueryfyAI's AI Data Analyst:

```bash
# Using curl with standard mode
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "your-session-id",
    "message": "Show me sales trends for Q4",
    "mode": "standard"
  }'

# Using curl with analyst mode (insight-rich responses)
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "your-session-id",
    "message": "Show me sales trends for Q4",
    "mode": "analyst",
    "include_chart": true
  }'
```

**Analyst mode returns:**
- SQL query with execution results
- Key findings (e.g., "Sales increased 23% compared to Q3")
- Confidence score (0.0-1.0)
- Auto-generated chart with recommended visualization type
- Data quality assessment (completeness, issues detected)

---

## Production Deployment

### Docker Compose (Recommended)

```bash
# 1. Configure environment
cp .env.production.example .env.production
# Edit .env.production with your settings

# 2. Generate SSL certificates (optional)
./scripts/generate-certs.sh

# 3. Deploy
./scripts/deploy.sh

# Or manually:
docker-compose -f docker-compose.production.yml up -d
```

### With Monitoring Stack

```bash
docker-compose -f docker-compose.production.yml \
               -f docker-compose.monitoring.yml up -d
```

This adds:
- **Prometheus** (:9090) - Metrics collection
- **Grafana** (:3001) - Dashboards and visualization
- **Redis Exporter** - Redis metrics
- **Node Exporter** - Host metrics

### Health Checks

```bash
# Quick health check
./scripts/healthcheck.sh

# Individual endpoints
curl http://localhost:8000/health        # Full health status
curl http://localhost:8000/health/live   # Liveness probe (Kubernetes)
curl http://localhost:8000/health/ready  # Readiness probe (Kubernetes)
```

### Operational Scripts

| Script | Purpose |
|--------|---------|
| `scripts/deploy.sh` | Zero-downtime deployment with health verification |
| `scripts/backup.sh` | Backup ChromaDB data and configuration |
| `scripts/restore.sh` | Restore from backup archive |
| `scripts/healthcheck.sh` | Verify all services are running |
| `scripts/generate-certs.sh` | Generate self-signed SSL certificates |

For detailed operational procedures, see [RUNBOOK.md](./RUNBOOK.md).

---

## Configuration

### Environment Variables

**Core Settings:**

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_NAME` | Application name | QueryfyAI |
| `DEBUG` | Enable debug mode | false |
| `LOG_LEVEL` | Logging level | INFO |
| `REDIS_URL` | Redis connection URL | redis://localhost:6379 |
| `ALLOWED_ORIGINS` | CORS allowed origins | * (restrict in production) |

**OAuth Gateway (Default LLM Provider):**

| Variable | Description | Required |
|----------|-------------|----------|
| `DEFAULT_LLM_BASE_URL` | OAuth gateway base URL | Yes |
| `DEFAULT_LLM_TOKEN_URL` | OAuth token endpoint | Yes |
| `DEFAULT_LLM_CLIENT_ID` | OAuth client ID | Yes |
| `DEFAULT_LLM_CLIENT_SECRET` | OAuth client secret | Yes |
| `DEFAULT_LLM_AUTH_SCOPE` | OAuth scope | Yes |
| `DEFAULT_LLM_MODEL` | Model name | gpt-4 |
| `DEFAULT_LLM_CHAT_ENDPOINT` | Chat completions endpoint | /v1/chat/completions |

**Session Settings:**

| Variable | Description | Default |
|----------|-------------|---------|
| `SESSION_EXPIRY_HOURS` | Session TTL | 24 |
| `TOKEN_REFRESH_BUFFER_SECONDS` | Refresh token before expiry | 300 |
| `MAX_CONTEXT_WINDOW` | Max conversation history | 20 |
| `MAX_HISTORY_ITEMS` | Max stored history items | 100 |

### LLM Provider Configuration

LLM provider is configured per-session. The default provider is OAuth Gateway for enterprise deployments.

**OAuth Gateway (Default):**
```json
{
  "provider": "oauth_gateway",
  "base_url": "https://llm-gateway.company.com",
  "token_url": "https://auth.company.com/oauth/token",
  "client_id": "your-client-id",
  "client_secret": "your-secret",
  "auth_scope": "llm.chat",
  "auth_type": "client_credentials",
  "model": "gpt-4"
}
```

**OpenAI:**
```json
{
  "provider": "openai",
  "api_key": "sk-...",
  "model": "gpt-4"
}
```

**Anthropic:**
```json
{
  "provider": "anthropic",
  "api_key": "sk-ant-...",
  "model": "claude-sonnet-4-20250514"
}
```

**Azure OpenAI:**
```json
{
  "provider": "azure",
  "base_url": "https://your-resource.openai.azure.com",
  "api_key": "your-azure-key",
  "model": "gpt-4-deployment"
}
```

**AWS Bedrock:**
```json
{
  "provider": "bedrock",
  "base_url": "us-east-1",
  "model": "anthropic.claude-3-sonnet-20240229-v1:0"
}
```
*Note: Uses AWS credentials from environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)*

**Google Gemini:**
```json
{
  "provider": "gemini",
  "api_key": "your-gemini-api-key",
  "model": "gemini-1.5-pro"
}
```

**Groq (Fast Inference):**
```json
{
  "provider": "groq",
  "api_key": "your-groq-api-key",
  "model": "llama-3.1-70b-versatile"
}
```

**Ollama (Local LLM):**
```json
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": "llama3"
}
```

See `.env.example` for full list of 15+ supported LLM providers.

### Database Connection URLs

| Database | Connection URL Format |
|----------|----------------------|
| PostgreSQL | `postgresql://user:pass@host:5432/dbname` |
| MySQL | `mysql://user:pass@host:3306/dbname` |
| SQL Server | `mssql://user:pass@host:1433/dbname` |
| Oracle | `oracle://user:pass@host:1521/SERVICE` |
| Snowflake | `snowflake://user:pass@account/db/schema?warehouse=WH` |
| BigQuery | `bigquery://project-id/dataset` |
| MongoDB | `mongodb://user:pass@host:27017/dbname` |
| Cassandra | `cassandra://user:pass@host:9042/keyspace` |
| DynamoDB | `dynamodb://region/` or `dynamodb://localhost:8000/` (local) |
| DuckDB | `duckdb:///path/to/database.duckdb` or `duckdb://:memory:` |
| SQLite | `sqlite:///path/to/database.db` or `sqlite:///:memory:` |
| ClickHouse | `clickhouse://user:pass@host:8123/dbname` |

---

## DML Operations (Data Modification)

QueryfyAI supports safe data modification operations (INSERT, UPDATE, DELETE) with multiple safety modes.

### Safety Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **Preview** | Shows affected rows without executing | Review changes before committing |
| **Sandbox** | Executes in transaction, then rolls back | Test changes safely |
| **Confirm** | Executes with explicit confirmation token | Production changes |

### Database DML Support

| Database | Modes Supported | Notes |
|----------|-----------------|-------|
| PostgreSQL, MySQL, SQL Server, Oracle | Preview, Sandbox, Confirm | Full ACID support |
| SQLite, DuckDB | Preview, Sandbox, Confirm | Full ACID support |
| MongoDB | Preview, Sandbox, Confirm | Requires replica set for transactions |
| Snowflake, BigQuery, ClickHouse | Preview, Confirm | No rollback - changes are immediate |
| Cassandra, DynamoDB | Not Supported | Use native tools |

### Security Features

- **Confirmation Tokens**: 5-minute expiry, single-use, bound to session
- **WHERE Required**: UPDATE/DELETE must have WHERE clause
- **Blocked Operations**: DROP, TRUNCATE, ALTER always blocked
- **Large Operation Warnings**: Alerts for operations affecting 100+ rows

---

## Database Migrations

QueryfyAI uses Alembic for database schema migrations. Migrations are required when using PostgreSQL for state persistence (Data Dictionary, session storage, etc.).

### Migration Commands

```bash
cd backend

# Apply all pending migrations
alembic upgrade head

# Check current migration status
alembic current

# View migration history
alembic history

# Rollback one migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade <revision_id>

# Generate new migration (auto-detect changes)
alembic revision --autogenerate -m "description of changes"

# Generate empty migration (manual)
alembic revision -m "description of changes"
```

### First-Time Setup

```bash
# 1. Ensure DATABASE_URL is configured in .env
export DATABASE_URL=postgresql://user:pass@localhost:5432/queryfyai

# 2. Create the database (if it doesn't exist)
createdb queryfyai

# 3. Run all migrations
alembic upgrade head
```

### Docker/Production Migrations

Migrations run automatically on container startup via the entrypoint script. For manual execution:

```bash
# In Docker
docker exec -it queryfyai-backend alembic upgrade head

# In Kubernetes
kubectl exec -it deploy/queryfyai-backend -- alembic upgrade head
```

---

## API Reference

All API endpoints use the `/api/v1/` prefix.

### Chat (Primary Endpoint)

The unified chat endpoint is the recommended way to interact with QueryfyAI.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/chat` | POST | **Primary endpoint** - Unified chat for all query modes |

**Chat Request:**
```jsonc
{
  "session_id": "uuid",
  "message": "Show me top 10 customers by revenue",
  "mode": "standard",       // or "analyst" for insight-rich answers
  "stream": true,           // Enable SSE streaming
  "include_chart": true,    // Auto-generate charts (analyst mode)
  "include_reasoning": false, // Include LLM reasoning trace
  "continue_conversation": true  // Enable multi-turn conversations
}
```

**Modes:**
- `standard`: Fast SQL generation (single LLM call, optimized for speed)
- `analyst`: Full analysis with SQL, execution, charts, key findings, and confidence scores

**Streaming Events (SSE):**
| Event | Description | Example Payload |
|-------|-------------|-----------------|
| `thinking` | Processing status updates | `{"event": "thinking", "content": "Analyzing question...", "progress": 0.1}` |
| `sql_chunk` | Progressive SQL tokens (standard mode) | `{"event": "sql_chunk", "content": "SELECT * FROM", "progress": 0.3}` |
| `sql_complete` | Final validated SQL | `{"event": "sql_complete", "content": "SELECT * FROM customers...", "progress": 0.9}` |
| `tool_call` | Tool invocation (analyst mode) | `{"event": "tool_call", "tool_name": "search_tables", "tool_args": {"query": "sales"}}` |
| `tool_result` | Tool execution results (analyst mode) | `{"event": "tool_result", "tool_name": "search_tables", "content": "Found 3 tables"}` |
| `executing` | Query execution status | `{"event": "executing", "content": "Running query...", "progress": 0.7}` |
| `analyzing` | Analysis in progress | `{"event": "analyzing", "content": "Generating insights...", "progress": 0.8}` |
| `done` | Final response with all data | `{"event": "done", "content": "Complete", "progress": 1.0, "data": {...}}` |
| `error` | Error occurred | `{"event": "error", "content": "SQL validation failed"}` |

**Analyst Mode Response Fields:**
```json
{
  "success": true,
  "mode": "analyst",
  "sql": "SELECT customer_id, SUM(amount) as revenue FROM orders GROUP BY customer_id ORDER BY revenue DESC LIMIT 10",
  "sql_hash": "abc123...",
  "answer": "Found 10 customers with total revenue ranging from $50K to $250K",
  "key_findings": [
    "Customer #1042 has the highest revenue at $250,000",
    "Top 3 customers account for 45% of total revenue",
    "Average order value for top customers is $5,200"
  ],
  "confidence": 0.92,
  "chart": {
    "chart_type": "bar",
    "title": "Top 10 Customers by Revenue",
    "x_axis": "customer_id",
    "y_axis": "revenue",
    "data": [...]
  },
  "data_quality": {
    "overall_score": 95,
    "completeness": 98,
    "issues": ["2% missing customer names"]
  },
  "raw_result": {
    "row_count": 10,
    "columns": ["customer_id", "revenue"],
    "sample_rows": [...]
  },
  "tools_used": ["search_tables", "execute_and_analyze"],
  "is_follow_up": false,
  "conversation_turn": 1
}
```

### Sessions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/sessions` | POST | Create new session with LLM and DB config |
| `/api/v1/sessions/{id}` | GET | Get session details |
| `/api/v1/sessions/{id}` | DELETE | Delete session |
| `/api/v1/sessions/{id}/test-llm` | POST | Test LLM connection |
| `/api/v1/sessions/{id}/test-db` | POST | Test database connection |
| `/api/v1/sessions/defaults` | GET | Get default configuration |

### Queries (Legacy - use `/chat` instead)

> **Note:** These endpoints are deprecated. Use `/api/v1/chat` for new integrations.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/query/generate` | POST | ⚠️ Deprecated - Use `/chat` with `mode: "standard"` |
| `/api/v1/query/generate/stream` | POST | ⚠️ Deprecated - Use `/chat` with `stream: true` |
| `/api/v1/query/explain` | POST | Get plain-language SQL explanation |
| `/api/v1/query/explain/stream` | POST | Stream SQL explanation (SSE) |
| `/api/v1/query/execute` | POST | Execute SQL query (read-only) |
| `/api/v1/query/export` | POST | Export results to Excel |

### DML Operations (Data Modification)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/dml/preview` | POST | Preview affected rows without executing |
| `/api/v1/dml/sandbox` | POST | Execute in transaction then rollback |
| `/api/v1/dml/execute` | POST | Execute with confirmation token |
| `/api/v1/dml/confirm` | POST | Generate confirmation token |

### Follow-up Queries

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/followup/generate` | POST | Generate follow-up SQL with context |
| `/api/v1/followup/classify` | POST | Classify query intent |

### Consolidated Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/consolidated/generate-and-execute` | POST | Generate and execute in one call |
| `/api/v1/consolidated/generate-and-execute/stream` | POST | Stream generation + execute (SSE) |

### Data Dictionary (Context Studio)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/data-dictionary/terms` | GET | List business terms |
| `/api/v1/data-dictionary/terms` | POST | Create business term |
| `/api/v1/data-dictionary/terms/{id}` | PUT | Update business term |
| `/api/v1/data-dictionary/terms/{id}` | DELETE | Delete business term |
| `/api/v1/data-dictionary/columns` | GET | List column descriptions |
| `/api/v1/data-dictionary/columns` | POST | Add column description |
| `/api/v1/data-dictionary/columns/bulk` | POST | Bulk add column descriptions |
| `/api/v1/data-dictionary/stats` | GET | Get data dictionary statistics |

### Schema

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/schema/refresh` | POST | Refresh database schema |
| `/api/v1/schema/{session_id}` | GET | Get cached schema |

### History Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/history/{session_id}` | GET | Get query history (paginated) |
| `/api/v1/history/{session_id}/search` | GET | Search query history |
| `/api/v1/history/{query_id}/pin` | POST | Pin a query |
| `/api/v1/history/{query_id}/unpin` | POST | Unpin a query |
| `/api/v1/history/{query_id}/reexecute` | POST | Re-execute historical query |
| `/api/v1/feedback` | POST | Submit query feedback |

**Generate Query Request:**
```json
{
  "session_id": "uuid",
  "natural_language": "Show me top 10 customers by revenue"
}
```

**Execute Query Request:**
```json
{
  "session_id": "uuid",
  "sql_query": "SELECT * FROM customers ORDER BY revenue DESC LIMIT 10",
  "limit": 500,
  "query_id": "uuid",
  "sql_hash": "sha256-hash"
}
```

### Health and Metrics

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Full health status |
| `/health/live` | GET | Liveness probe |
| `/health/ready` | GET | Readiness probe |
| `/metrics` | GET | Prometheus metrics |

---

## Security

### Multi-Layer Defense

1. **Input Validation**: All inputs validated against strict schemas
2. **Prompt Injection Detection**: Pattern matching for injection attempts
3. **SQL Validation**: Only SELECT/WITH queries allowed
4. **Output Sanitization**: SQL cleaned of markdown, comments, multi-statements
5. **Session Locking**: Configuration frozen after first query
6. **Rate Limiting**: Nginx-level rate limiting (10 req/s)

### Prompt Injection Prevention

The security service detects and blocks:
- Instruction override attempts ("ignore previous instructions")
- System prompt injections
- Roleplay/jailbreak attempts ("act as DBA")
- Encoded command sequences (base64, hex)
- SQL injection via natural language

### SQL Security

- **Whitelist-only**: Only SELECT and WITH (CTE) queries
- **Blocked patterns**: INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, GRANT, EXEC
- **Comment stripping**: Single-line and multi-line comments removed
- **Multi-statement blocking**: Semicolons rejected
- **Automatic LIMIT**: Enforced on all queries

### Security Headers

All responses include:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: default-src 'self'`

---

## Monitoring & Observability

### Prometheus Metrics

Available at `/metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `queryfyai_requests_total` | Counter | Total requests by endpoint |
| `queryfyai_requests_success` | Counter | Successful requests |
| `queryfyai_requests_error` | Counter | Failed requests |
| `queryfyai_queries_generated` | Counter | SQL queries generated |
| `queryfyai_queries_executed` | Counter | SQL queries executed |
| `queryfyai_active_sessions` | Gauge | Current active sessions |
| `queryfyai_uptime_seconds` | Counter | Application uptime |
| `queryfyai_llm_requests_total` | Counter | LLM API calls by provider |
| `queryfyai_llm_tokens_total` | Counter | Total tokens used |
| `queryfyai_db_queries_total` | Counter | Database queries by type |

### OpenTelemetry Distributed Tracing

QueryfyAI supports distributed tracing via OpenTelemetry with Jaeger integration.

**Enable Tracing:**

```bash
# In .env
OTEL_ENABLED=true
OTEL_SERVICE_NAME=queryfyai-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

**With Docker Compose (includes Jaeger):**

```bash
docker-compose -f docker-compose.production.yml \
               -f docker-compose.monitoring.yml up -d
```

**Access Jaeger UI:** `http://localhost:16686`

**Traced Operations:**
- HTTP requests (FastAPI auto-instrumentation)
- LLM API calls (provider, model, tokens)
- Database queries (type, duration, rows)
- Agent execution steps (validation, retry attempts)
- Redis operations (cache hits/misses)

### Grafana Dashboard

Pre-configured dashboard includes:
- Backend/Redis status indicators
- Request rate by status code
- Response time percentiles (p50, p95, p99)
- Redis metrics (connections, keys)
- System resources (CPU, memory)

### Alert Rules

Configured alerts for:
- Service down (backend, Redis)
- High error rate (>10% in 5 minutes)
- High response time (p95 > 5s)
- Memory pressure

---

## Troubleshooting

For common issues and solutions, see [TROUBLESHOOTING.md](./TROUBLESHOOTING.md).

### Quick Diagnostics

```bash
# Check all services
./scripts/healthcheck.sh

# View logs
docker-compose -f docker-compose.production.yml logs -f backend

# Check specific endpoint
curl http://localhost:8000/health | jq
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Redis connection failed | Normal - app falls back to in-memory storage |
| Token refresh errors | Verify OAuth credentials and token URL |
| Schema extraction timeout | Increase timeout or reduce schema complexity |
| CORS errors | Set `ALLOWED_ORIGINS` environment variable |

---

## Project Structure

```
nl2sql-app/
├── backend/
│   ├── app/
│   │   ├── api/                    # API route handlers
│   │   │   ├── sessions.py         # Session management endpoints
│   │   │   ├── queries.py          # Query generation/execution
│   │   │   ├── schema.py           # Schema retrieval
│   │   │   ├── followup.py         # Follow-up query handling
│   │   │   └── consolidated.py     # Combined endpoints
│   │   ├── core/                   # Configuration and utilities
│   │   │   ├── config.py           # Environment settings
│   │   │   ├── constants.py        # Application constants
│   │   │   └── csrf_utils.py       # CSRF token handling
│   │   ├── middleware/             # Request processing
│   │   │   └── rate_limit.py       # Rate limiting
│   │   ├── models/                 # Pydantic schemas
│   │   └── services/
│   │       ├── executors/          # Database query executors
│   │       │   ├── postgresql.py   # PostgreSQL executor
│   │       │   ├── mysql.py        # MySQL executor
│   │       │   ├── mongodb.py      # MongoDB executor
│   │       │   ├── cassandra.py    # Cassandra CQL executor
│   │       │   ├── dynamodb.py     # DynamoDB PartiQL executor
│   │       │   ├── duckdb.py       # DuckDB executor
│   │       │   └── sqlite.py       # SQLite executor
│   │       ├── schema_extractors/  # Schema extraction per DB type
│   │       │   ├── postgresql.py   # PostgreSQL schema
│   │       │   ├── mysql.py        # MySQL schema
│   │       │   ├── mongodb.py      # MongoDB schema
│   │       │   ├── cassandra.py    # Cassandra schema (keyspaces, partition keys)
│   │       │   ├── dynamodb.py     # DynamoDB schema (tables, GSI/LSI)
│   │       │   └── generic_sql.py  # Generic SQL fallback
│   │       ├── prompt_providers/   # Database-specific LLM prompts
│   │       │   ├── base.py         # Base prompt provider
│   │       │   ├── sql.py          # SQL database prompts
│   │       │   ├── mongodb.py      # MongoDB MQL prompts
│   │       │   ├── cassandra.py    # Cassandra CQL prompts
│   │       │   └── dynamodb.py     # DynamoDB PartiQL prompts
│   │       ├── validators/         # Security validation
│   │       │   ├── prompt_injection.py  # 26+ attack patterns
│   │       │   └── sql_injection.py     # SQL security
│   │       ├── followup/           # Conversation context
│   │       │   ├── classifier.py   # Query intent detection
│   │       │   └── sql_transformer.py   # SQL modification
│   │       ├── _future/            # Ready-to-activate features
│   │       │   ├── data_dictionary.py   # Business glossary (95%)
│   │       │   └── tenant_manager.py    # Multi-tenant (100%)
│   │       ├── llm_service.py      # LiteLLM-based LLM interface
│   │       ├── database_service.py # Database connection management
│   │       ├── cache_service.py    # Redis/memory caching
│   │       ├── sql_agent.py        # Self-healing SQL agent
│   │       ├── vector_db.py        # ChromaDB/Qdrant RAG
│   │       └── session_store.py    # Redis session management
│   ├── tests/                      # Pytest tests (60%+ coverage)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── layout/             # App structure
│   │   │   │   ├── AppShell.vue    # Main layout container
│   │   │   │   ├── AppHeader.vue   # Header with theme toggle
│   │   │   │   ├── HistorySidebar.vue   # Collapsible history
│   │   │   │   └── SettingsDrawer.vue   # LLM/DB configuration
│   │   │   ├── chat/               # Conversation display
│   │   │   │   ├── ChatContainer.vue    # Message list
│   │   │   │   ├── AIResponseCard.vue   # AI response with results
│   │   │   │   └── UserMessage.vue      # User query bubble
│   │   │   ├── input/              # Query input area
│   │   │   │   ├── QueryInput.vue       # Main input component
│   │   │   │   ├── SuggestionsPanel.vue # Schema-aware suggestions
│   │   │   │   └── InputOptions.vue     # Stream/agentic toggles
│   │   │   ├── results/            # Query results
│   │   │   │   └── ResultsExpander.vue  # Collapsible results
│   │   │   ├── setup/              # Initial setup
│   │   │   │   └── SetupWizard.vue      # Connection wizard
│   │   │   ├── ChartView.vue       # Smart visualizations
│   │   │   ├── ChartCustomizer.vue # Chart customization
│   │   │   └── ActivityPanel.vue   # Query history list
│   │   ├── composables/            # Vue composition utilities
│   │   │   ├── useConversation.js  # Chat message management
│   │   │   ├── useToast.js         # Toast notifications
│   │   │   └── useQueryOptions.js  # Streaming/agentic state
│   │   ├── stores/                 # Pinia state stores
│   │   │   └── activity.js         # Query history (localStorage)
│   │   ├── utils/
│   │   │   ├── api.js              # Backend API client
│   │   │   └── chartAnalyzer/      # Smart chart type detection
│   │   ├── styles/
│   │   │   ├── main.css            # Global styles
│   │   │   └── design-tokens.css   # Theme variables
│   │   └── App.vue                 # Root component
│   ├── Dockerfile.production
│   └── nginx.production.conf
├── k8s/                            # Kubernetes manifests
│   ├── deployment.yaml
│   ├── ingress.yaml
│   └── kustomization.yaml
├── monitoring/
│   ├── prometheus.yml
│   ├── alerts/
│   └── grafana/
├── scripts/
│   ├── deploy.sh                   # Zero-downtime deployment
│   ├── backup.sh                   # ChromaDB backup
│   └── healthcheck.sh              # Service verification
├── docs/
│   ├── ARCHITECTURE.md             # System architecture & diagrams
│   ├── ROADMAP.md                  # Product roadmap
│   ├── ONBOARDING.md               # Getting started guide
│   └── QUERYFYAI_OVERVIEW.md       # Product overview
├── docker-compose.yml              # Development
├── docker-compose.dev.yml          # Full dev stack
├── docker-compose.nosql.yml        # NoSQL testing (Cassandra, DynamoDB Local)
├── docker-compose.production.yml   # Production deployment
├── docker-compose.monitoring.yml   # Prometheus/Grafana stack
└── RUNBOOK.md                      # Operational procedures
```

---

## CI/CD

### GitHub Actions Workflows

| Workflow | Trigger | Description |
|----------|---------|-------------|
| `ci.yml` | Push/PR to main | Run tests, lint, build Docker images |
| `release.yml` | Tag v*.*.* | Build release images, create GitHub release |
| `deploy-trigger.yml` | Manual | Trigger deployment to target environment |

### Pipeline Stages

1. **Test**: Run pytest with Redis service
2. **Lint**: Check code style (ruff/eslint)
3. **Build**: Multi-stage Docker builds
4. **Push**: Push to container registry (on main/tags)
5. **Release**: Create GitHub release with artifacts

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Write tests for new functionality
4. Ensure all tests pass (`pytest`)
5. Commit with conventional commits (`feat:`, `fix:`, `docs:`)
6. Submit a pull request

---

## License

MIT License - see [LICENSE](./LICENSE) file for details.

---

## Related Documentation

- [docs/ONBOARDING.md](./docs/ONBOARDING.md) - Getting started guide for developers
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) - System architecture, components, and technical deep dives
- [docs/AGENT_REFERENCE.md](./docs/AGENT_REFERENCE.md) - ReAct agent API, configuration, workflows, and troubleshooting
- [docs/CONTEXT_STUDIO.md](./docs/CONTEXT_STUDIO.md) - Business terms, schema context, and query patterns
- [docs/TOOL_DEVELOPMENT.md](./docs/TOOL_DEVELOPMENT.md) - Guide for building custom agent tools
- [docs/ANALYSIS_TOOLS_GUIDE.md](./docs/ANALYSIS_TOOLS_GUIDE.md) - Analysis engine and LLM-assisted insights
- [docs/SECURITY.md](./docs/SECURITY.md) - Prompt injection protection, PII handling, and security configuration
- [docs/ROADMAP.md](./docs/ROADMAP.md) - Product roadmap, competitive landscape, and future direction
