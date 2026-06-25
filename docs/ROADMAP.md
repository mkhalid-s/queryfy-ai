# Roadmap

> **Last Updated**: February 2026 | **Current Version**: 1.2.0

## Vision

QueryfyAI aims to be the most secure, production-ready open-source NL2SQL platform for
enterprise integration. Unlike library-focused tools (Vanna AI) or desktop clients (Chat2DB),
QueryfyAI is an API-first platform with built-in security, observability, and an agentic
architecture that delivers not just SQL but actionable insights. The goal is a single intelligent
interface where users ask questions in natural language and receive answers -- with automatic
analysis, error recovery, and visualization -- adapted to the complexity of each query.

---

## Current Capabilities

### Core Query Engine

- **Natural language to SQL** generation with Chain-of-Thought reasoning and few-shot learning
- **19 database types** supported, including NoSQL (MongoDB MQL, Cassandra CQL, DynamoDB PartiQL)
- **15+ LLM providers** via LiteLLM, with OAuth gateway support for enterprise LLM deployments
- **Streaming responses** via SSE with 9 event types (thinking, tool calls, execution, analysis)
- **Self-correcting SQL** generation with automatic retry on syntax or schema errors
- **Unified `/chat` API** endpoint for all query modes (standard and analyst)

### ReAct Agent (Analyst Mode, v1.2.0)

- **15 specialized tools** organized into three categories:
  - Schema discovery (5): search tables, get schema, lookup business terms, find similar queries, get sample data
  - Execution (2): execute and analyze, validate columns
  - Analysis (8): detect insights, analyze statistics, recommend chart, prepare chart data, get query metadata, and more
- **5 analysis engines**: insight detection, statistics, data quality, comparisons, chart intelligence
- **Multi-turn conversations** with context-aware follow-ups (5-turn window)
- **Self-healing error recovery**: error classification (permanent vs transient), circuit breakers, retry with backoff
  - Permanent error threshold: 3 (schema/syntax)
  - Transient error threshold: 5 (connection/timeout)
  - Exploration iteration limit: 7 (prevents infinite loops)
- **Answer generation** with key findings, confidence scores, and chart recommendations
- **Agent state management** with checkpointer backends (in-memory, PostgreSQL)
- **Memory protection**: 50MB safety threshold, result sampling above 1000 rows

### Context Studio

- Visual metadata and business glossary management
- Business term definitions with SQL expressions
- Auto-population from schema documentation
- Industry research shows ~27% accuracy improvement from business context

### Security

- Multi-layer SQL injection prevention (regex, AST, keyword analysis)
- Prompt injection detection (26+ patterns)
- HMAC-signed sessions with SQL integrity binding
- CSRF token-based protection
- Rate limiting (configurable per endpoint)
- DML safety with preview/sandbox/confirm workflow
- Read-only enforcement for query execution

### Operations

- Docker and Kubernetes-ready deployment with health probes
- Prometheus metrics and pre-built Grafana dashboards
- Backup/restore scripts for operational confidence
- CI/CD workflows (GitHub Actions)
- Redis-backed session management with configurable eviction

### Frontend

- Vue 3 SPA with Composition API and Pinia state management
- Smart chart recommendations (15+ chart types via ECharts)
- Agent timeline visualization showing tool calls and reasoning steps
- Insight cards, data quality indicators, follow-up suggestions
- Dark/light mode, Excel export, conversational UI
- Setup wizard for initial configuration

---

## Competitive Landscape

### Comparison

| Dimension | QueryfyAI | Vanna AI | Wren AI | Dataherald |
|-----------|-----------|----------|---------|------------|
| **Architecture** | API-first platform | Python library | GenBI platform | Enterprise API |
| **Database Support** | 19 (incl. NoSQL) | 10+ (SQL only) | 10 (SQL only) | 4 (SQL only) |
| **Security** | Multi-layer (prompt injection, HMAC, CSRF, rate limiting) | Basic | RBAC, basic | Basic |
| **Analysis** | ReAct agent, 5 engines, auto-insights | RAG + Plotly viz | Semantic layer (MDL) | RAG agent + fine-tuning |
| **Deployment** | K8s, Prometheus, health probes, backup scripts | Docker, manual | Docker, cloud option | Docker, complex setup |
| **License** | MIT | MIT | AGPL-3.0 | Apache 2.0 |
| **Stars (approx)** | New | 14k | 10k | 3.5k |

### Differentiation

QueryfyAI occupies a unique position: it combines the security depth needed for enterprise
adoption (prompt injection detection, HMAC session signing, SQL integrity checks) with
production-grade operations (Kubernetes readiness, Prometheus metrics, health probes) and an
agentic architecture that goes beyond SQL generation to deliver automated analysis.

Key unique strengths:
- **Only** open-source NL2SQL with comprehensive NoSQL support (MongoDB, Cassandra, DynamoDB)
- **Only** platform with multi-layer prompt injection detection (26+ patterns)
- **Only** solution with production observability stack (Prometheus + Grafana) out of the box
- **Only** tool with OAuth gateway support for enterprise LLM routing

### Known Gaps vs Competitors

| Gap | Competitors That Have It | Priority |
|-----|--------------------------|----------|
| User authentication (JWT/RBAC) | Vanna 2.0, Chat2DB, Wren AI, Dataherald | Critical |
| Semantic layer / MDL | Wren AI | Medium |
| Fine-tuning pipeline | Chat2DB (own 7B model), Dataherald | Medium |
| Admin UI | Wren AI, Dataherald | Medium |
| Slack/Teams integration | Vanna AI, Dataherald | Low |

---

## Near-term Priorities (Next 3-6 Months)

These priorities are derived from the gap analysis between agentic and non-agentic modes,
the competitive landscape, and the adaptive enrichment strategy.

### 1. Unify on Agentic Architecture

**Problem**: Two separate code paths exist -- agentic (`/chat`) and non-agentic (`/query/*`).
The non-agentic path is a strict subset of agentic capabilities, missing 10+ features:
error recovery, natural language answers, key findings, confidence scores, chart recommendations,
data quality metrics, tool orchestration, conversation context, circuit breakers, and memory
protection.

**Plan**:
- Build a compatibility layer that routes legacy `/query/*` endpoints to the agentic backend
- Add feature flags for gradual rollout (10% -> 50% -> 100%)
- Deprecate legacy endpoints with 90-day sunset notice
- Remove non-agentic code paths after migration

**Success criteria**: All queries processed through agentic architecture, legacy endpoints
deprecated, single codebase to maintain.

### 2. Adaptive Enrichment (Intent-Based Response Depth)

**Problem**: Users must manually choose between standard and analyst mode. Simple queries waste
tokens with unnecessary analysis; complex queries may not get needed insights in standard mode.

**Plan**:
- Implement intent detection classifying 8 query types: SQL generation, data retrieval,
  analytical, diagnostic, exploratory, schema inquiry, follow-up, comparative
- Map each intent to an enrichment configuration (execute, insights, key findings, charts,
  data quality, natural language answer)
- Remove mode selection from API and UI
- Add user overrides for forcing enrichment level when needed

**Success criteria**: 85%+ intent classification accuracy, 30-50% token savings on mixed
workloads, no mode selection needed by users.

### 3. Authentication and Access Control

**Problem**: No user authentication exists. This is the top blocker for enterprise adoption
and open-source credibility -- every major competitor already has it.

**Plan**:
- JWT authentication with token refresh
- API key support for programmatic access
- Basic RBAC with three roles: admin, user, viewer
- Session-to-user binding for audit trails

### 4. Expand Database Support

**Problem**: Despite supporting 19 database types via the executor infrastructure, several
high-demand databases are missing: SQLite, Snowflake, BigQuery, Oracle.

**Plan**: Add connectors for these four databases to close the gap with Vanna AI (10+) and
Chat2DB (15+). The executor pattern is well-established; each new database requires a
dialect-specific executor and connection configuration.

### 5. Test Coverage

**Backend** (target: 80%+ coverage):
- Agent error recovery scenarios (permanent vs transient errors)
- Circuit breaker threshold behavior
- Conversation follow-up detection accuracy
- Tool orchestration edge cases
- Memory protection limits
- Streaming event ordering

**Frontend** (target: component + E2E):
- Vue component tests for chat flow, Context Studio, results display
- E2E test suite covering agentic chat, streaming events, and conversation flow

### 6. Admin Dashboard

Build a basic admin UI covering:
- Database connection management
- Feature flag configuration
- Usage monitoring and query history
- User management (once auth is implemented)

This reduces configuration burden (currently requires environment variables or config files)
and aligns with what Wren AI and Dataherald already offer.

### 7. Observability Improvements

- Agent iteration metrics: time per reasoning step, tool usage distribution
- Tool execution time tracking by tool type
- LLM token usage dashboards per user and session
- Connection pool utilization metrics
- Query performance profiling with slow query alerts
- Circuit breaker trip frequency monitoring

---

## Future Direction

### Adaptive Intelligence

Move toward a single intelligent mode that adjusts response depth automatically based on user
intent. This eliminates the agentic/non-agentic split entirely, simplifies the codebase to a
single code path, and optimizes token costs without sacrificing response quality.

The intent detection system classifies 8 query types (SQL generation, data retrieval,
analytical, diagnostic, exploratory, schema inquiry, follow-up, comparative) and maps each to
an enrichment configuration controlling execution, insights, charts, data quality checks, and
natural language answers. Simple queries like "generate SQL for top 10 customers" skip analysis
entirely (~76% token savings), while diagnostic queries like "why did sales drop?" get full
enrichment. Average savings on mixed workloads: 40-50%.

A fallback strategy defaults uncertain queries to full enrichment -- better to over-enrich
than miss needed insights.

### Enterprise Governance

Build compliance and governance features for regulated environments:

- **Intelligent approval workflows**: Risk-based query approval before execution, with
  automatic classification of query risk level
- **Row-level security**: Automatic WHERE clause injection based on user role, ensuring
  users only see data they are authorized to access
- **Compliance dashboards**: Visual audit trails with reports for SOX, HIPAA, and GDPR
- **Multi-tenant support**: Full tenant isolation for SaaS deployment. Implementation code
  already exists in `_future/tenant_manager.py` and needs integration and testing

### Scaling Architecture

Move from the current single-instance model (~100 concurrent users) toward horizontal scaling
across three tiers:

- **Tier 1 (100-500 users)**: Increase worker count, expand connection pools, move agent state
  to PostgreSQL, add query result caching with fingerprint-based deduplication
- **Tier 2 (500-2000 users)**: Distributed agent state across instances, task queue system
  (Celery/RQ) for long-running agent runs, parallel tool execution in the ReAct agent,
  sliding window rate limiting
- **Tier 3 (2000+ users)**: Pure async architecture (remove ThreadPoolExecutor), read/write
  pool separation, regional caching, priority queue for cost-based query scheduling

Key resilience patterns to implement: bulkhead isolation (separate pools for standard vs
analyst workloads), timeout cascades (tool timeout < agent timeout < request timeout),
graceful degradation (fallback to standard mode under load).

### Learning and Improvement Loop

Implement a feedback-based improvement pipeline:

- Collect user corrections on generated SQL and analysis
- Use corrections for RAG enhancement and few-shot example curation
- Build a fine-tuning pipeline for domain-specific query patterns
- LLM ensemble voting: multiple models vote on best SQL for high-stakes queries, with
  confidence scoring to surface disagreements

Target: 15% accuracy improvement from fine-tuning on domain data within 12 months.

### Integration Ecosystem

Expand beyond the web UI to meet users where they already work:

- **Chat integrations**: Slack and Teams bot templates
- **Developer tools**: Jupyter integration, Python SDK
- **Embedding**: Web components for embedding QueryfyAI in existing applications
- **Enterprise SSO**: SAML and OIDC support for corporate identity providers
- **Query scheduling**: Automated recurring queries with alerting (no competitor offers this)

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for how to contribute to these roadmap items.
