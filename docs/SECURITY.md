# Security

nl2sql-app is designed with security at multiple layers: from prompt injection prevention and PII detection to session isolation and SQL parameterization.

---

## Contents

1. [Threat Model](#threat-model)
2. [Prompt Injection Protection](#prompt-injection-protection)
3. [SQL Injection Prevention](#sql-injection-prevention)
4. [Session Isolation](#session-isolation)
5. [PII Handling](#pii-handling)
6. [DML Safety](#dml-safety)
7. [Security Configuration](#security-configuration)
8. [Fine-tuning Considerations](#fine-tuning-considerations)

---

## Threat Model

### What the system defends against

| Threat | Defense Layer |
|--------|--------------|
| **Prompt injection** via user queries | Input sanitization, 26+ regex patterns, validator chain |
| **Prompt injection** via stored data dictionary entries | Write-time validation, read-time sanitization |
| **SQL injection** via natural language input | SQL injection pattern detection, read-only enforcement |
| **SQL tampering** between generation and execution | HMAC-SHA256 integrity binding |
| **Session hijacking or forgery** | Signed session IDs (HMAC), CSRF tokens |
| **Cross-database data access** | `connection_hash` ownership validation |
| **Destructive SQL operations** | Write-keyword blocking, DML safety modes |
| **Resource exhaustion** | Rate limiting, result size limits, query timeouts |
| **Sensitive field exposure during schema extraction** | Pattern-based sensitive field detection |
| **Error message information leakage** | Error sanitization, credential redaction |

### What is out of scope

- **Authentication and authorization**: The system does not implement user authentication or role-based access control. It is expected to run behind an authenticating proxy or within a trusted network.
- **Encryption at rest**: Database credentials and session data are stored without application-level encryption. Use infrastructure-level encryption (e.g., encrypted volumes, managed secrets).
- **Network-level security**: TLS termination, firewall rules, and network segmentation are expected to be handled by the deployment infrastructure (Nginx, cloud provider).
- **PII redaction in query results**: The system can mark columns as PII in the data dictionary, but does not currently redact PII values from query results. See [PII Handling](#pii-handling).

---

## Prompt Injection Protection

The system uses a defense-in-depth approach with multiple layers that check for prompt injection at different points in the pipeline.

### Layer 1: Input sanitization (user queries)

When a user submits a natural language query, `SecurityService.sanitize_input()` in `backend/app/services/security.py` runs a validator chain that checks against two pattern sets:

**Prompt injection patterns** (26+ patterns) detect attempts to override LLM instructions:

| Category | Example patterns |
|----------|-----------------|
| Instruction overrides | `ignore previous instructions`, `disregard all`, `forget everything` |
| Role manipulation | `you are now`, `act as if`, `pretend to be`, `roleplay as` |
| System prompt access | `show me your prompt`, `reveal your instructions` |
| Delimiter injection | `` ```system ``, `[[system]]`, `<system>` |
| Jailbreak attempts | `jailbreak`, `bypass filter`, `developer mode`, `admin mode` |
| Token boundary injection | `<\|im_start\|>`, `[INST]`, `### System` |

If any pattern matches, the request is blocked with a security warning and an audit event is logged.

### Layer 2: Data dictionary write-time validation

Business terms, column descriptions, and other dictionary entries are validated for prompt injection before being stored. This prevents an attacker from embedding malicious instructions in metadata that later gets injected into LLM prompts.

The `_check_prompt_injection()` function in `backend/app/services/data_dictionary.py:85-109` checks the following fields at write time:

- Business term `definition` and `sql_expression`
- Column description `description` and `business_name`
- Bulk import entries (each row validated individually)

The validation uses 21 compiled regex patterns (defined at `data_dictionary.py:52-82`) covering:
- Instruction overrides (5 patterns)
- Role manipulation (5 patterns)
- System prompt access (4 patterns)
- Delimiter injection (3 patterns)
- Jailbreak keywords (4 patterns)

If a match is found, the write is rejected with a `ValueError` explaining which field triggered the detection.

### Layer 3: Data dictionary read-time sanitization

Even with write-time validation, dictionary content is re-checked before being included in LLM prompts. `SQLGenerationService._sanitize_dictionary_value()` in `backend/app/services/sql_generation.py:124-136` applies the same pattern set. If a stored value fails sanitization (e.g., it was written before validation was added), it is silently excluded from the prompt context and a warning is logged.

This creates a defense-in-depth pipeline:

```
User input --> [Layer 1: Input validation] --> blocked if malicious
                                                    |
                                               LLM prompt assembly
                                                    |
Dictionary content --> [Layer 2: Write-time check] --> rejected if malicious
                            |
                       [Layer 3: Read-time check] --> excluded if suspicious
                            |
                       Included in prompt
```

### Audit logging

All security events are logged via `AuditLogger.log_security_event()` with structured fields including session ID, event type, and a preview of the triggering content. Events logged include:
- `INPUT_SANITIZED` -- prompt or SQL injection detected in user input
- `UNSAFE_SQL_GENERATED` -- LLM-generated SQL failed safety validation

---

## SQL Injection Prevention

### Input-level detection

`SecurityService.SQL_INJECTION_PATTERNS` in `backend/app/services/security.py:1027-1048` detects SQL injection attempts embedded in natural language input:

| Pattern | Purpose |
|---------|---------|
| `; DROP ...` / `; DELETE ...` | Stacked query injection |
| `-- ` / `/* ... */` | Comment-based injection |
| `INTO OUTFILE` / `LOAD_FILE()` | File system access |
| `EXEC()` / `xp_cmdshell` | Command execution |
| `SLEEP()` / `BENCHMARK()` / `pg_sleep` | Time-based blind injection |
| `0x...` (long hex) / `CHAR()` | Encoded payload injection |
| `CONCAT(...SELECT` / `CONVERT(...SELECT` | Nested injection |

### Generated SQL validation

After the LLM generates SQL, `SecurityService.validate_generated_sql()` enforces read-only operations using the `QueryValidatorRegistry` (Strategy pattern). Validation is database-specific:

- **SQL databases** (PostgreSQL, MySQL, etc.): Only `SELECT` and `WITH` (CTE) statements are allowed. Dangerous keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `EXEC`, `MERGE`, `CALL`, `DECLARE`, `SET`) are blocked.
- **MongoDB**: Only read operations (`find`, `aggregate`, `count`, `distinct`) are allowed. Write operations and dangerous chaining patterns (`.forEach()`, `.deleteMany()`) are blocked.
- **Cassandra (CQL)**: `SELECT` only.
- **DynamoDB (PartiQL)**: `SELECT` only.

### SQL integrity verification (HMAC)

The `SQLIntegrityService` in `backend/app/services/security.py:451-911` binds generated SQL to its session to prevent tampering between generation and execution:

1. When SQL is generated, it is registered with an HMAC-SHA256 hash: `HMAC(session_secret, session_id + query_id + sql)`
2. The hash is stored server-side (Redis with in-memory fallback)
3. When the user executes the SQL, the hash is re-verified before execution
4. Each SQL registration is single-use and expires after 1 hour

This ensures that only server-generated SQL can be executed -- a client cannot modify the SQL and still pass verification.

### Result size limits

`ResultSizeLimiter` enforces output constraints to prevent resource exhaustion:
- Maximum rows: configurable via `MAX_EXPORT_ROWS` (default: 1M)
- Maximum payload size: configurable via `MAX_RESULT_BYTES` (default: 500MB)
- Maximum cell length: 10,000 characters per cell

---

## Session Isolation

### Signed session IDs

`SessionTokenService` in `backend/app/services/security.py:124-186` creates HMAC-signed session IDs in the format `uuid:timestamp:signature`. The signature is verified on every request to ensure the session was created by this server instance. Sessions expire after 30 days.

### CSRF protection

`CSRFProtection` in `backend/app/services/security.py:188-279` generates per-session CSRF tokens with 1-hour expiry. Tokens are stored in Redis (with in-memory fallback for single-instance deployments). All state-modifying data dictionary endpoints require a valid CSRF token via the `verify_csrf_token` dependency.

### Connection hash ownership

Data dictionary entries (business terms, column descriptions, query patterns) are scoped by `connection_hash` -- a SHA256-derived identifier of the database connection URL. Every API endpoint that reads or modifies dictionary data:

1. Derives the `connection_hash` from the caller's session
2. Verifies the requested resource belongs to that `connection_hash`
3. Returns 404 if the resource belongs to a different connection

This prevents users connected to one database from viewing or modifying dictionary entries belonging to another database. See `backend/app/api/data_dictionary.py` where every GET, PUT, and DELETE endpoint performs this ownership check (e.g., lines 357-358, 376-377, 394-395).

### Rate limiting

Per-session and per-endpoint rate limiting is implemented to prevent abuse. Limits are enforced at the application level.

---

## PII Handling

### Current state: detection and labeling

The system provides PII detection and labeling at two levels:

**1. Automatic detection during schema extraction**

`SensitiveFieldMixin` in `backend/app/services/schema_extractors/sensitive_field_mixin.py` detects fields with names matching sensitive patterns:

```
password, token, secret, email, ssn, phone, address,
key, hash, credit, card, cvv, pin, auth, credential
```

This mixin is used by MongoDB, DynamoDB, and Cassandra schema extractors. When a field matches, it is flagged during extraction (e.g., sample data is not collected for that field).

**2. Manual PII marking in data dictionary**

Users can mark columns as `is_pii` or `is_sensitive` via the Context Studio UI or API. These flags are stored in the `ColumnDescription` model and surfaced in:
- The enhanced schema endpoint (`GET /api/v1/data-dictionary/schema/enhanced/{session_id}`)
- Column context injected into LLM prompts (tagged with `[PII]`)

### What is NOT implemented

- **Result redaction**: Query results are returned in full regardless of PII flags. There is no server-side masking, filtering, or redaction of PII columns in query output.
- **Access control for PII columns**: No role-based restrictions on who can query PII data.
- **Audit trail for PII access**: No logging of when PII columns are accessed via queries.

These capabilities are designed but not yet built.

---

## DML Safety

For databases that support data modification (INSERT, UPDATE, DELETE), the system implements a three-mode safety protocol:

| Mode | Behavior | Risk |
|------|----------|------|
| **Preview** | Converts the DML statement to an equivalent SELECT to show which rows would be affected | None -- no changes made |
| **Sandbox** | Executes the DML inside a transaction, shows affected row count, then rolls back | None -- changes rolled back |
| **Confirm** | Generates a single-use confirmation token (5-minute expiry), requires explicit user confirmation, then commits | Changes applied |

Safety constraints enforced on all DML operations:
- `WHERE` clause is required for `UPDATE` and `DELETE`
- `DROP`, `TRUNCATE`, and `ALTER` are always blocked
- Confirmation tokens are session-bound, single-use, and stored in Redis for multi-instance support

---

## Security Configuration

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_SECRET` | (auto-generated) | HMAC signing key for sessions and SQL integrity. Set this to a stable value in production to survive restarts. |
| `DEBUG` | `false` | When `true`, error messages include full details. Set to `false` in production. |
| `MAX_EXPORT_ROWS` | `1000000` | Maximum rows returned in query results |
| `MAX_RESULT_BYTES` | `524288000` | Maximum result payload size in bytes (500MB) |
| `CORS_ORIGINS` | `*` | Allowed CORS origins. Restrict to your frontend domain in production. |
| `RATE_LIMIT_ENABLED` | `true` | Enable per-session rate limiting |
| `REDIS_URL` | (none) | Redis connection URL for distributed CSRF tokens, SQL registry, and session storage |

### Deployment recommendations

1. **Always set `SERVER_SECRET`** to a cryptographically random value that persists across deployments. If not set, a new secret is generated on each restart, invalidating all active sessions and CSRF tokens.

2. **Use Redis** in production for CSRF tokens and SQL integrity storage. Without Redis, these are stored in-memory and lost on restart or unavailable across multiple backend instances.

3. **Restrict CORS origins** to your frontend domain. The default `*` is suitable only for development.

4. **Run behind a reverse proxy** (Nginx) with:
   - TLS termination
   - Rate limiting (10 req/s recommended)
   - Security headers (CSP, X-Frame-Options, X-Content-Type-Options)

5. **Use read-only database credentials** for the target database connection. The application enforces read-only at the query level, but a read-only database user provides defense in depth.

6. **Set `DEBUG=false`** in production to prevent detailed error messages from leaking internal information (connection strings, file paths, stack traces).

---

## Fine-tuning Considerations

The system stores successful query patterns for few-shot learning. If you use these patterns to fine-tune an LLM or feed them into RAG retrieval, keep the following in mind:

### Data quality

- Query patterns are auto-captured on successful execution. Not all successful queries are high-quality examples.
- Use the `is_curated` flag to distinguish manually reviewed patterns from auto-captured ones.
- Use the `rating` field (user feedback) to filter for patterns that users found useful.
- Export patterns via `GET /api/v1/data-dictionary/export/terms` for external processing.

### Security of training data

- All dictionary content (terms, column descriptions) is validated for prompt injection at write time. However, query patterns (`natural_query` and `sql` fields) are not currently validated for injection content because they represent actual user queries and SQL.
- Before using exported patterns for fine-tuning, review them for:
  - Queries that reference specific table/column names you do not want to expose
  - SQL that encodes business logic you consider proprietary
  - Accidental PII in natural language queries (e.g., "show me John Smith's orders")

### Scope isolation

- Query patterns are scoped by `connection_hash`. Patterns from one database connection are not visible to or used by another.
- Business terms support hierarchical scoping: `global > database > tenant > session`. Be aware that global terms are shared across all connections.

---

## Related files

| File | Purpose |
|------|---------|
| `backend/app/services/security.py` | Core security: CSRF, SQL integrity, input sanitization, rate limiting |
| `backend/app/services/validators/` | Validator chain for prompt and SQL injection detection |
| `backend/app/services/data_dictionary.py` | Write-time prompt injection validation for dictionary content |
| `backend/app/services/sql_generation.py` | Read-time sanitization of dictionary content before LLM prompts |
| `backend/app/services/schema_extractors/sensitive_field_mixin.py` | Sensitive field auto-detection patterns |
| `backend/app/api/data_dictionary.py` | API endpoints with CSRF and ownership validation |
| `backend/app/core/csrf_utils.py` | CSRF token verification dependency |

---

## Related documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) -- System architecture and security architecture overview
