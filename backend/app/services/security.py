"""
QueryfyAI - Security Service

Comprehensive security including:
- Prompt injection prevention
- SQL injection prevention
- SQL integrity verification (hash-based)
- Session-bound SQL execution
- Signed session tokens (HMAC)
- CSRF protection (Redis-backed for distributed deployment)
- Error sanitization
- Result size limits
- Audit logging
- Rate limiting support (Redis-backed for distributed deployment)
"""

import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Server secret for signing (generate once, persist in production)
# Uses settings from config.py which loads from .env file
SERVER_SECRET = settings.SESSION_SIGNING_SECRET or secrets.token_hex(32)

if not settings.SESSION_SIGNING_SECRET:
    if not settings.DEBUG:
        logger.error(
            "SESSION_SIGNING_SECRET not set in production - application startup will fail",
            detail=(
                "Set SESSION_SIGNING_SECRET in .env. A missing secret is treated as a "
                "fatal configuration error when DEBUG=False."
            ),
        )
    else:
        logger.warning(
            "SESSION_SIGNING_SECRET not set (DEBUG mode)",
            detail="Using random secret. Sessions will not persist across server restarts.",
        )


# ============================================================================
# REDIS HELPER FOR DISTRIBUTED DEPLOYMENT
# ============================================================================


class RedisHelper:
    """
    Redis helper for distributed deployment.
    Provides Redis connection with automatic fallback to in-memory.
    Thread-safe singleton initialization.
    """

    _instance = None
    _redis_client = None
    _initialized = False
    _init_lock = None  # Class-level lock for thread-safe init

    def __new__(cls):
        if cls._instance is None:
            import threading

            cls._init_lock = threading.Lock()
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Double-checked locking pattern for thread-safe initialization
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:  # Check again inside lock
                return
            self._init_redis()
            RedisHelper._initialized = True  # Set on class to ensure visibility

    def _init_redis(self):
        """Initialize Redis connection"""
        try:
            import redis

            self._redis_client = redis.Redis.from_url(
                settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2
            )
            self._redis_client.ping()
            logger.info("Security services: Redis connected (distributed mode enabled)")
        except Exception as e:
            logger.warning(
                f"Security services: Redis not available ({e}) - using in-memory (single-worker only)"
            )
            self._redis_client = None

    @property
    def client(self):
        """Get Redis client (may be None if unavailable)"""
        return self._redis_client

    @property
    def available(self) -> bool:
        """Check if Redis is available"""
        if not self._redis_client:
            return False
        try:
            self._redis_client.ping()
            return True
        except Exception:
            return False


# Global Redis helper instance
_redis_helper = RedisHelper()


class SessionTokenService:
    """
    Signed session tokens to prevent session ID guessing/forgery.
    Uses HMAC to sign session IDs so only server-generated sessions are valid.
    """

    @staticmethod
    def create_signed_session_id() -> str:
        """Create a new session ID with HMAC signature"""
        # Generate random session ID
        session_uuid = secrets.token_hex(16)
        timestamp = str(int(time.time()))

        # Create signature
        message = f"{session_uuid}:{timestamp}".encode("utf-8")
        signature = hmac.new(
            SERVER_SECRET.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()[
            :16
        ]  # Use first 16 chars of signature

        # Format: uuid:timestamp:signature
        return f"{session_uuid}:{timestamp}:{signature}"

    @staticmethod
    def verify_session_id(session_id: str) -> Tuple[bool, str]:
        """
        Verify that a session ID was created by this server.
        Returns (is_valid, message)

        Expected format: uuid:timestamp:signature (signed by server)
        """
        try:
            parts = session_id.split(":")
            if len(parts) != 3:
                return False, "Invalid session ID format"

            session_uuid, timestamp, provided_sig = parts

            # Verify signature
            message = f"{session_uuid}:{timestamp}".encode("utf-8")
            expected_sig = hmac.new(
                SERVER_SECRET.encode("utf-8"), message, hashlib.sha256
            ).hexdigest()[:16]

            if not hmac.compare_digest(provided_sig, expected_sig):
                logger.warning(
                    "Invalid session signature", session_id_prefix=session_id[:20]
                )
                return False, "Invalid session signature"

            # Check timestamp isn't too old (max 30 days)
            session_time = int(timestamp)
            max_age = 30 * 24 * 3600  # 30 days
            if time.time() - session_time > max_age:
                return False, "Session expired"

            return True, "Valid"

        except Exception as e:
            logger.error("Session verification error", error=str(e))
            return False, "Session verification failed"


class CSRFProtection:
    """
    CSRF token generation and verification.
    Supports Redis for distributed deployment with in-memory fallback.
    """

    REDIS_PREFIX = "csrf:"
    TOKEN_EXPIRY_SECONDS = 3600  # 1 hour

    def __init__(self) -> None:
        # In-memory fallback store: {session_id: {token: expiry_time}}
        self._tokens: Dict[str, Dict[str, float]] = defaultdict(dict)

    def _get_redis_key(self, session_id: str, token: str) -> str:
        """Get Redis key for a CSRF token"""
        return f"{self.REDIS_PREFIX}{session_id}:{token}"

    def generate_token(self, session_id: str) -> str:
        """Generate a CSRF token for the session"""
        token = secrets.token_hex(32)
        expiry = time.time() + self.TOKEN_EXPIRY_SECONDS

        # Clean old tokens for this session
        self._cleanup_session_tokens(session_id)

        # Store in Redis if available
        if _redis_helper.available:
            try:
                key = self._get_redis_key(session_id, token)
                _redis_helper.client.setex(key, self.TOKEN_EXPIRY_SECONDS, "1")
            except Exception as e:
                logger.warning(f"Redis CSRF store failed: {e}")
                # Fall back to memory
                self._tokens[session_id][token] = expiry
        else:
            # Store in memory
            self._tokens[session_id][token] = expiry

        return token

    def verify_token(self, session_id: str, token: str) -> Tuple[bool, str]:
        """Verify a CSRF token"""
        if not token:
            return False, "CSRF token required"

        # Check Redis first if available
        if _redis_helper.available:
            try:
                key = self._get_redis_key(session_id, token)
                if _redis_helper.client.exists(key):
                    return True, "Valid"
                # Token not in Redis, might be in memory fallback
            except Exception as e:
                logger.warning(f"Redis CSRF verify failed: {e}")

        # Check memory store (fallback or primary)
        if session_id not in self._tokens:
            return False, "No CSRF tokens for session"

        if token not in self._tokens[session_id]:
            return False, "Invalid CSRF token"

        # Check expiry
        if time.time() > self._tokens[session_id][token]:
            del self._tokens[session_id][token]
            return False, "CSRF token expired"

        return True, "Valid"

    def _cleanup_session_tokens(self, session_id: str):
        """Remove expired tokens for a session (memory store only, Redis auto-expires)"""
        now = time.time()
        if session_id in self._tokens:
            self._tokens[session_id] = {
                t: exp for t, exp in self._tokens[session_id].items() if exp > now
            }

    def cleanup_session(self, session_id: str):
        """Clean up all tokens for a session"""
        # Clean Redis tokens
        if _redis_helper.available:
            try:
                pattern = f"{self.REDIS_PREFIX}{session_id}:*"
                keys = _redis_helper.client.keys(pattern)
                if keys:
                    _redis_helper.client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis CSRF cleanup failed: {e}")

        # Clean memory store
        if session_id in self._tokens:
            del self._tokens[session_id]


class ErrorSanitizer:
    """
    Sanitize error messages for production to prevent information leakage.
    """

    # Patterns that might leak sensitive information in error messages.
    # Order matters: URL credentials and specific token shapes must match
    # before the generic "token=" key=value pattern, otherwise the
    # generic pattern wins on its prefix substring.
    SENSITIVE_PATTERNS = [
        # URL-embedded credentials
        (r"://[^:/\s]+:[^@\s]+@", "://***:***@"),
        # AWS access keys (AKIA / ASIA prefix, 16 chars after)
        (r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "***AWS_KEY***"),
        # GitHub PATs (classic + fine-grained + app)
        (r"\bghp_[A-Za-z0-9]{36,}\b", "***GH_PAT***"),
        (r"\bghs_[A-Za-z0-9]{36,}\b", "***GH_SECRET***"),
        (r"\bgho_[A-Za-z0-9]{36,}\b", "***GH_OAUTH***"),
        (r"\bghu_[A-Za-z0-9]{36,}\b", "***GH_USER***"),
        (r"\bghr_[A-Za-z0-9]{36,}\b", "***GH_REFRESH***"),
        (r"\bgithub_pat_[A-Za-z0-9_]{60,}\b", "***GH_FG_PAT***"),
        # GitLab PATs (glpat-)
        (r"\bglpat-[A-Za-z0-9_-]{20,}\b", "***GL_PAT***"),
        # Slack tokens (xoxb / xoxa / xoxp / xoxs)
        (r"\bxox[abps]-[A-Za-z0-9-]{10,}\b", "***SLACK_TOKEN***"),
        # JWT bearer tokens (eyJ prefix is base64-encoded {"alg":...)
        (
            r"\bBearer\s+eyJ[A-Za-z0-9_=-]+\.[A-Za-z0-9_=-]+\.[A-Za-z0-9_.+/=-]+",
            "Bearer ***JWT***",
        ),
        (
            r"\beyJ[A-Za-z0-9_=-]+\.[A-Za-z0-9_=-]+\.[A-Za-z0-9_.+/=-]+",
            "***JWT***",
        ),
        # Generic Bearer tokens that aren't JWT-shaped (catches opaque
        # bearer tokens; must come after the JWT-specific match above)
        (r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", "Bearer ***"),
        # Generic key/secret/password/token patterns (key=value shape).
        # Must come last so the specific shapes above match first.
        (r'password["\s:=]+[^\s,}]+', "password=***"),
        (r'api[_-]?key["\s:=]+[^\s,}]+', "api_key=***"),
        (r'secret["\s:=]+[^\s,}]+', "secret=***"),
        (r'token["\s:=]+[^\s,}]+', "token=***"),
    ]

    # Pre-compiled for the hot path (sanitize_error fires on every tool
    # error; the 27 wired catch-sites compound under error storms).
    _COMPILED_SENSITIVE_PATTERNS = [
        (re.compile(p, re.IGNORECASE), repl) for p, repl in SENSITIVE_PATTERNS
    ]

    # Generic messages for common error types
    GENERIC_MESSAGES = {
        "connection": "Database connection failed. Please check your connection settings.",
        "authentication": "Authentication failed. Please verify your credentials.",
        "timeout": "Request timed out. Please try again.",
        "permission": "Permission denied. You do not have access to this resource.",
        "not_found": "The requested resource was not found.",
        "validation": "Invalid input. Please check your request parameters.",
        "rate_limit": "Too many requests. Please wait before trying again.",
        "internal": "An internal error occurred. Please try again later.",
    }

    # Database errors that are safe to show to users (they help understand query issues)
    DATABASE_ERROR_PATTERNS = [
        "does not exist",
        "undefined table",
        "undefined column",
        "syntax error",
        "invalid input syntax",
        "column .* does not exist",
        "relation .* does not exist",
        "operator does not exist",
        "data type mismatch",
        "division by zero",
        "null value",
        "duplicate key",
        "foreign key constraint",
        "check constraint",
        "unique constraint",
    ]

    @classmethod
    def sanitize_error(cls, error: Exception, is_production: Optional[bool] = None) -> str:
        """
        Sanitize error message for client response.
        Database query errors are shown to help users understand issues.
        Sensitive system errors get generic messages in production.
        """
        if is_production is None:
            is_production = not settings.DEBUG

        error_str = str(error)
        error_lower = error_str.lower()

        # Database errors should always be shown (they help users fix their queries)
        for pattern in cls.DATABASE_ERROR_PATTERNS:
            if pattern in error_lower or re.search(pattern, error_lower):
                return cls._redact_sensitive(error_str)

        if is_production:
            # Return generic message based on error type
            if "connection" in error_lower or "connect" in error_lower:
                return cls.GENERIC_MESSAGES["connection"]
            elif (
                "auth" in error_lower
                or "password" in error_lower
                or "credential" in error_lower
            ):
                return cls.GENERIC_MESSAGES["authentication"]
            elif "timeout" in error_lower or "timed out" in error_lower:
                return cls.GENERIC_MESSAGES["timeout"]
            elif (
                "permission" in error_lower
                or "denied" in error_lower
                or "forbidden" in error_lower
            ):
                return cls.GENERIC_MESSAGES["permission"]
            elif "not found" in error_lower or "404" in error_lower:
                return cls.GENERIC_MESSAGES["not_found"]
            elif "valid" in error_lower or "invalid" in error_lower:
                return cls.GENERIC_MESSAGES["validation"]
            elif "rate" in error_lower or "limit" in error_lower:
                return cls.GENERIC_MESSAGES["rate_limit"]
            else:
                return cls.GENERIC_MESSAGES["internal"]
        else:
            # Development: sanitize but show detail
            return cls._redact_sensitive(error_str)

    @classmethod
    def _redact_sensitive(cls, text: str) -> str:
        """Redact sensitive information from text"""
        result = text
        for compiled, replacement in cls._COMPILED_SENSITIVE_PATTERNS:
            result = compiled.sub(replacement, result)
        return result

    @classmethod
    def safe_log_error(cls, error: Exception) -> str:
        """Create a safe version of error for logging (redacts sensitive data)"""
        return cls._redact_sensitive(str(error))


class ResultSizeLimiter:
    """
    Limit result set sizes to prevent memory exhaustion.
    """

    # Limits - configurable via environment variables
    MAX_ROWS = settings.MAX_EXPORT_ROWS  # Default: 1 million rows
    MAX_BYTES = settings.MAX_RESULT_BYTES  # Default: 500MB
    MAX_CELL_LENGTH = 10000  # Max characters per cell

    @classmethod
    def check_and_limit_results(
        cls, results: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Check result size and apply limits if needed.
        Returns (limited_results, warnings)
        """
        warnings: List[str] = []

        if "rows" not in results:
            return results, warnings

        rows = results["rows"]

        # Check row count
        if len(rows) > cls.MAX_ROWS:
            warnings.append(
                f"Results truncated from {len(rows)} to {cls.MAX_ROWS} rows"
            )
            rows = rows[: cls.MAX_ROWS]

        # Check total size
        try:
            total_size = len(json.dumps(rows))
            if total_size > cls.MAX_BYTES:
                # Progressively reduce rows until under limit
                while len(rows) > 100 and len(json.dumps(rows)) > cls.MAX_BYTES:
                    rows = rows[: len(rows) // 2]
                warnings.append(
                    f"Results truncated due to size limit ({cls.MAX_BYTES // 1024 // 1024}MB)"
                )
        except (TypeError, ValueError) as e:
            logger.debug("Could not serialize results for size check", error=str(e))

        # Truncate individual cells that are too long
        truncated_cells = 0
        for row in rows:
            for key, value in row.items():
                if isinstance(value, str) and len(value) > cls.MAX_CELL_LENGTH:
                    row[key] = value[: cls.MAX_CELL_LENGTH] + "... [truncated]"
                    truncated_cells += 1

        if truncated_cells > 0:
            warnings.append(f"{truncated_cells} cell(s) truncated due to length")

        results["rows"] = rows
        results["row_count"] = len(rows)

        return results, warnings


class SQLIntegrityService:
    """
    Ensures SQL integrity between generation and execution.
    Prevents tampering and session hijacking.
    Supports Redis for distributed deployment with in-memory fallback.
    """

    REDIS_PREFIX_SQL = "sqlreg:"
    REDIS_PREFIX_SECRET = "sqlsec:"
    SQL_EXPIRY_SECONDS = 3600  # 1 hour

    def __init__(self) -> None:
        # In-memory fallback: {session_id: {query_id: {hash, sql, created_at, executed}}}
        self._sql_registry: Dict[str, Dict[str, Dict]] = defaultdict(dict)
        # Session secrets for HMAC signing (in-memory fallback)
        self._session_secrets: Dict[str, str] = {}

    def _get_redis_sql_key(self, session_id: str, query_id: str) -> str:
        """Get Redis key for SQL registry entry"""
        return f"{self.REDIS_PREFIX_SQL}{session_id}:{query_id}"

    def _get_redis_secret_key(self, session_id: str) -> str:
        """Get Redis key for session secret"""
        return f"{self.REDIS_PREFIX_SECRET}{session_id}"

    def get_session_secret(self, session_id: str) -> str:
        """Get or create a secret key for the session"""
        # Try Redis first
        if _redis_helper.available:
            try:
                key = self._get_redis_secret_key(session_id)
                secret = _redis_helper.client.get(key)
                if secret:
                    return secret
                # Create new secret
                secret = secrets.token_hex(32)
                _redis_helper.client.setex(
                    key, self.SQL_EXPIRY_SECONDS * 24, secret
                )  # 24h expiry
                return secret
            except Exception as e:
                logger.warning(f"Redis secret retrieval failed: {e}")

        # In-memory fallback
        if session_id not in self._session_secrets:
            self._session_secrets[session_id] = secrets.token_hex(32)
        return self._session_secrets[session_id]

    def generate_sql_hash(self, session_id: str, sql: str) -> str:
        """Generate HMAC hash for SQL bound to session"""
        secret = self.get_session_secret(session_id)
        # Include session_id in hash to bind SQL to session
        message = f"{session_id}:{sql}".encode("utf-8")
        return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def register_sql(self, session_id: str, query_id: str, sql: str) -> str:
        """
        Register generated SQL with its hash.
        Returns the hash that must be provided for execution.
        """
        sql_hash = self.generate_sql_hash(session_id, sql)

        entry_data = {
            "hash": sql_hash,
            "sql": sql,
            "created_at": datetime.now().isoformat(),
            "executed": False,
            "execution_count": 0,
        }

        # Store in Redis if available
        if _redis_helper.available:
            try:
                key = self._get_redis_sql_key(session_id, query_id)
                _redis_helper.client.setex(
                    key, self.SQL_EXPIRY_SECONDS, json.dumps(entry_data)
                )
            except Exception as e:
                logger.warning(f"Redis SQL register failed: {e}")
                # Fall back to memory
                entry_data["created_at"] = datetime.now()
                self._sql_registry[session_id][query_id] = entry_data
        else:
            # Store in memory
            entry_data["created_at"] = datetime.now()
            self._sql_registry[session_id][query_id] = entry_data

        logger.info(
            "SQL registered",
            session_id=session_id[:8],
            query_id=query_id[:8],
            hash_prefix=sql_hash[:16],
        )
        return sql_hash

    def _get_registry_entry(self, session_id: str, query_id: str) -> Optional[Dict]:
        """Get registry entry from Redis or memory"""
        # Try Redis first
        if _redis_helper.available:
            try:
                key = self._get_redis_sql_key(session_id, query_id)
                data = _redis_helper.client.get(key)
                if data:
                    entry = json.loads(data)
                    entry["created_at"] = datetime.fromisoformat(entry["created_at"])
                    return entry
            except Exception as e:
                logger.warning(f"Redis SQL retrieval failed: {e}")

        # Check memory
        if (
            session_id in self._sql_registry
            and query_id in self._sql_registry[session_id]
        ):
            return self._sql_registry[session_id][query_id]

        return None

    def verify_sql(
        self,
        session_id: str,
        query_id: str,
        sql: str,
        provided_hash: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Verify SQL integrity before execution.
        Checks:
        1. SQL was generated in this session
        2. SQL hasn't been tampered with
        3. SQL hasn't expired
        4. Hash matches if provided
        """
        # Try to get entry from Redis or memory
        registry_entry = (
            self._get_registry_entry(session_id, query_id) if query_id else None
        )

        if registry_entry:
            # Check expiry
            age = datetime.now() - registry_entry["created_at"]
            if age.total_seconds() > self.SQL_EXPIRY_SECONDS:
                return (
                    False,
                    f"SQL expired. Please regenerate (max age: {self.SQL_EXPIRY_SECONDS}s)",
                )

            # Verify SQL matches registered SQL
            if registry_entry["sql"] != sql:
                logger.warning(
                    "SQL TAMPERING DETECTED",
                    session_id=session_id[:8],
                    query_id=query_id[:8],
                )
                AuditLogger.log_security_event(
                    session_id,
                    "SQL_TAMPERING",
                    f"Original: {registry_entry['sql'][:100]}... | Received: {sql[:100]}...",
                )
                return False, "SQL integrity check failed. The query has been modified."

            # Verify hash if provided
            if provided_hash:
                expected_hash = self.generate_sql_hash(session_id, sql)
                if not hmac.compare_digest(provided_hash, expected_hash):
                    logger.warning("SQL HASH MISMATCH", session_id=session_id[:8])
                    return False, "SQL hash verification failed."

            return True, "SQL verified"

        # No entry found - try session history fallback
        logger.debug(
            "No SQL in registry, trying session history fallback",
            session_id=session_id[:8] if session_id else "None",
        )
        try:
            from app.services.session_store import session_store

            session = session_store.get(session_id)
            if session and session.get("history"):
                self.restore_from_history(session_id, session["history"])
                # Re-check after restoration
                registry_entry = (
                    self._get_registry_entry(session_id, query_id) if query_id else None
                )
                if registry_entry and registry_entry["sql"] == sql:
                    return True, "SQL verified (from history)"

                # Check all entries in memory for SQL match
                if session_id in self._sql_registry:
                    for qid, entry in self._sql_registry[session_id].items():
                        if entry["sql"] == sql:
                            age = datetime.now() - entry["created_at"]
                            if age.total_seconds() <= self.SQL_EXPIRY_SECONDS:
                                return True, "SQL verified"
        except Exception as e:
            logger.warning("Failed to restore from session history", error=str(e))

        return (
            False,
            "SQL not found in session. You can only execute SQL that was generated in this session.",
        )

    def mark_executed(self, session_id: str, query_id: str):
        """Mark SQL as executed for audit purposes"""
        # Update in Redis if available
        if _redis_helper.available:
            try:
                key = self._get_redis_sql_key(session_id, query_id)
                data = _redis_helper.client.get(key)
                if data:
                    entry = json.loads(data)
                    entry["executed"] = True
                    entry["execution_count"] = entry.get("execution_count", 0) + 1
                    ttl = _redis_helper.client.ttl(key)
                    if ttl > 0:
                        _redis_helper.client.setex(key, ttl, json.dumps(entry))
            except Exception as e:
                logger.warning(f"Redis mark executed failed: {e}")

        # Update memory as well
        if (
            session_id in self._sql_registry
            and query_id in self._sql_registry[session_id]
        ):
            self._sql_registry[session_id][query_id]["executed"] = True
            self._sql_registry[session_id][query_id]["execution_count"] += 1

    def restore_from_history(self, session_id: str, history: List[Dict]):
        """
        Restore SQL registry from session history.
        Called when a session is restored after server restart.
        """
        if not history:
            return

        restored_count = 0
        for entry in history:
            query_id = entry.get("id")
            sql = entry.get("sql")
            if query_id and sql:
                # Re-register the SQL
                sql_hash = self.generate_sql_hash(session_id, sql)
                entry_data = {
                    "hash": sql_hash,
                    "sql": sql,
                    "created_at": datetime.now(),
                    "executed": True,
                    "execution_count": 1,
                }
                self._sql_registry[session_id][query_id] = entry_data

                # Also store in Redis if available
                if _redis_helper.available:
                    try:
                        key = self._get_redis_sql_key(session_id, query_id)
                        redis_entry = entry_data.copy()
                        redis_entry["created_at"] = redis_entry[
                            "created_at"
                        ].isoformat()
                        _redis_helper.client.setex(
                            key, self.SQL_EXPIRY_SECONDS, json.dumps(redis_entry)
                        )
                    except Exception:
                        pass

                restored_count += 1

        if restored_count > 0:
            logger.info(
                "SQL registry restored",
                session_id=session_id[:8],
                entries=restored_count,
            )

    def cleanup_session(self, session_id: str):
        """Clean up SQL registry when session ends"""
        # Clean Redis entries
        if _redis_helper.available:
            try:
                # Clean SQL entries
                pattern = f"{self.REDIS_PREFIX_SQL}{session_id}:*"
                keys = _redis_helper.client.keys(pattern)
                if keys:
                    _redis_helper.client.delete(*keys)
                # Clean session secret
                secret_key = self._get_redis_secret_key(session_id)
                _redis_helper.client.delete(secret_key)
            except Exception as e:
                logger.warning(f"Redis SQL cleanup failed: {e}")

        # Clean memory stores
        if session_id in self._sql_registry:
            del self._sql_registry[session_id]
        if session_id in self._session_secrets:
            del self._session_secrets[session_id]

    def cleanup_expired(self):
        """Remove expired SQL entries (memory store only, Redis auto-expires)"""
        now = datetime.now()
        for session_id in list(self._sql_registry.keys()):
            for query_id in list(self._sql_registry[session_id].keys()):
                entry = self._sql_registry[session_id][query_id]
                age = now - entry["created_at"]
                if age.total_seconds() > self.SQL_EXPIRY_SECONDS * 2:
                    del self._sql_registry[session_id][query_id]


class RateLimiter:
    """
    Rate limiting to prevent brute force and DoS attacks.
    Supports Redis for distributed deployment with in-memory fallback.
    """

    REDIS_PREFIX = "ratelimit:"

    def __init__(self) -> None:
        # In-memory fallback: {session_id: [(timestamp, endpoint), ...]}
        self._requests: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
        # Use centralized rate limits from constants
        from app.core.constants import RATE_LIMITS

        self.RATE_LIMITS = RATE_LIMITS

    def _get_redis_key(self, session_id: str, endpoint: str) -> str:
        """Get Redis key for rate limiting"""
        return f"{self.REDIS_PREFIX}{session_id}:{endpoint}"

    def check_rate_limit(self, session_id: str, endpoint: str) -> Tuple[bool, str]:
        """
        Check if request is within rate limits.
        Returns (allowed, message)
        """
        limit, window = self.RATE_LIMITS.get(endpoint, self.RATE_LIMITS["default"])

        # Use Redis if available (distributed rate limiting)
        if _redis_helper.available:
            try:
                key = self._get_redis_key(session_id, endpoint)
                current = _redis_helper.client.get(key)

                if current is None:
                    # First request in window
                    _redis_helper.client.setex(key, window, 1)
                    return True, "OK"

                current_count = int(current)
                if current_count >= limit:
                    logger.warning(
                        "Rate limit exceeded",
                        session_id=session_id[:8],
                        endpoint=endpoint,
                    )
                    return (
                        False,
                        f"Rate limit exceeded. Max {limit} requests per {window}s for {endpoint}.",
                    )

                # Increment counter
                _redis_helper.client.incr(key)
                return True, "OK"
            except Exception as e:
                logger.warning(f"Redis rate limit check failed: {e}")
                # Fall through to memory-based limiting

        # In-memory fallback
        now = time.time()

        # Clean old requests
        self._requests[session_id] = [
            (ts, ep) for ts, ep in self._requests[session_id] if now - ts < window
        ]

        # Count requests for this endpoint
        endpoint_requests = sum(
            1 for ts, ep in self._requests[session_id] if ep == endpoint
        )

        if endpoint_requests >= limit:
            logger.warning(
                "Rate limit exceeded", session_id=session_id[:8], endpoint=endpoint
            )
            return (
                False,
                f"Rate limit exceeded. Max {limit} requests per {window}s for {endpoint}.",
            )

        # Record this request
        self._requests[session_id].append((now, endpoint))
        return True, "OK"

    def cleanup_session(self, session_id: str):
        """Clean up when session ends"""
        # Clean Redis keys
        if _redis_helper.available:
            try:
                pattern = f"{self.REDIS_PREFIX}{session_id}:*"
                keys = _redis_helper.client.keys(pattern)
                if keys:
                    _redis_helper.client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis rate limit cleanup failed: {e}")

        # Clean memory store
        if session_id in self._requests:
            del self._requests[session_id]


class AuditLogger:
    """
    Security audit logging for compliance and forensics.
    """

    _log_file = None

    @classmethod
    def log_sql_execution(
        cls,
        session_id: str,
        query_id: str,
        sql: str,
        success: bool,
        row_count: int = 0,
        error: Optional[str] = None,
    ):
        """Log SQL execution for audit"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id[:16] + "...",
            "query_id": query_id[:16] + "..." if query_id else None,
            "sql_preview": sql[:200] + "..." if len(sql) > 200 else sql,
            "success": success,
            "row_count": row_count,
            "error": error,
        }
        logger.info("AUDIT_SQL_EXECUTION", **log_entry)

    @classmethod
    def log_security_event(cls, session_id: str, event_type: str, details: str):
        """Log security events (tampering, injection attempts, etc.)"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "session_id": session_id[:16] + "..." if session_id else None,
            "details": details[:500],
        }
        logger.warning(f"SECURITY_{event_type}", **log_entry)

    @classmethod
    def log_session_event(cls, session_id: str, event_type: str, details: Optional[str] = None):
        """Log session lifecycle events"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id[:16] + "...",
            "details": details,
        }
        logger.info(f"AUDIT_SESSION_{event_type}", **log_entry)


# Global instances
sql_integrity = SQLIntegrityService()
rate_limiter = RateLimiter()
csrf_protection = CSRFProtection()


class QueryLanguageRegistry:
    """
    Registry mapping database types to their query languages.
    This provides a single source of truth for validation rules.
    """

    # Query language types
    SQL = "sql"
    MONGODB = "mongodb"
    CQL = "cql"  # Cassandra Query Language
    PARTIQL = "partiql"  # DynamoDB PartiQL

    # Map each database type to its query language
    DB_QUERY_LANGUAGES = {
        # SQL-based relational databases
        "postgresql": SQL,
        "mysql": SQL,
        "sqlserver": SQL,
        "oracle": SQL,
        # SQL-based cloud data warehouses
        "snowflake": SQL,
        "bigquery": SQL,
        "redshift": SQL,
        "databricks": SQL,
        # SQL-based analytics engines
        "clickhouse": SQL,
        "athena": SQL,
        "trino": SQL,
        "presto": SQL,
        "hive": SQL,
        "spark": SQL,
        # Document databases
        "mongodb": MONGODB,
        # NoSQL with SQL-like languages
        "cassandra": CQL,
        "dynamodb": PARTIQL,
    }

    @classmethod
    def get_query_language(cls, db_type: str) -> str:
        """Get the query language for a database type. Defaults to SQL."""
        return cls.DB_QUERY_LANGUAGES.get(db_type, cls.SQL)

    @classmethod
    def is_sql_database(cls, db_type: str) -> bool:
        """Check if database uses SQL query language."""
        return cls.get_query_language(db_type) == cls.SQL

    @classmethod
    def is_mongodb(cls, db_type: str) -> bool:
        """Check if database is MongoDB."""
        return cls.get_query_language(db_type) == cls.MONGODB

    @classmethod
    def is_cassandra(cls, db_type: str) -> bool:
        """Check if database is Cassandra (uses CQL)."""
        return cls.get_query_language(db_type) == cls.CQL

    @classmethod
    def is_dynamodb(cls, db_type: str) -> bool:
        """Check if database is DynamoDB (uses PartiQL)."""
        return cls.get_query_language(db_type) == cls.PARTIQL

    @classmethod
    def get_supported_databases(cls) -> List[str]:
        """Get list of all supported database types."""
        return list(cls.DB_QUERY_LANGUAGES.keys())

    @classmethod
    def get_databases_by_language(cls, language: str) -> List[str]:
        """Get all databases that use a specific query language."""
        return [db for db, lang in cls.DB_QUERY_LANGUAGES.items() if lang == language]


class SecurityService:
    """Comprehensive security for prompt injection and SQL injection prevention"""

    # Prompt injection patterns
    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+(previous|above|all)\s+instructions",
        r"disregard\s+(previous|above|all)",
        r"forget\s+(everything|all|previous)",
        r"you\s+are\s+now",
        r"new\s+instructions?:",
        r"system\s*:",
        r"<\s*system\s*>",
        r"\]\s*\[\s*system",
        r"act\s+as\s+(if|a)",
        r"pretend\s+(you|to)",
        r"roleplay\s+as",
        r"jailbreak",
        r"bypass\s+(filter|security|restriction)",
        r"execute\s+immediately",
        r"run\s+this\s+code",
        r"ignore\s+safety",
        r"override\s+instructions",
        r"admin\s+mode",
        r"developer\s+mode",
        r"<\|im_start\|>",
        r"<\|im_end\|>",
        r"\[INST\]",
        r"\[/INST\]",
        r"###\s*(Human|Assistant|System)",
        r"```\s*(system|admin|root)",
    ]

    # SQL injection patterns (for user input sanitization)
    # Note: These patterns detect injection attempts, not legitimate SQL features
    # Removed patterns that block legitimate queries:
    #   - information_schema/sys.tables - valid for metadata queries
    #   - UNION SELECT - valid for combining result sets (analytics queries)
    SQL_INJECTION_PATTERNS = [
        r";\s*(drop|delete|truncate|alter|create|insert|update|grant|revoke)\s+",
        # SQL comments (-- and /* */) are NOT blocked here because:
        # 1. Queries are LLM-generated, not raw user input
        # 2. DANGEROUS_SQL_KEYWORDS already blocks write ops even after comments
        # 3. sanitize_sql_for_execution strips comments before execution
        # UNION is allowed - legitimate for combining result sets
        # Injection risk is mitigated by: query must start with SELECT/WITH, no write operations
        r"into\s+(out|dump)file",
        r"load_file\s*\(",
        r"exec\s*\(",
        r"execute\s*\(",
        r"xp_cmdshell",
        r"sp_executesql",
        r"benchmark\s*\(",
        r"sleep\s*\(",
        r"waitfor\s+delay",
        r"pg_sleep",
        r"0x[0-9a-fA-F]{8,}",
        r"char\s*\(\s*\d+\s*\)",
        r"concat\s*\([^)]*select",
        r"convert\s*\([^)]*select",
    ]

    # Dangerous SQL keywords for write operations
    DANGEROUS_SQL_KEYWORDS = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "MERGE",
        "CALL",
        "DECLARE",
        "SET",
    ]

    @classmethod
    def sanitize_input(cls, text: str) -> Tuple[str, List[str]]:
        """
        Sanitize user input and return warnings.

        Uses the Chain of Responsibility pattern with validators for:
        - Prompt injection detection
        - SQL injection detection
        - Suspicious character sanitization

        Returns: (sanitized_text, list_of_warnings)
        """
        # Import here to avoid circular imports
        from app.services.validators import sanitize_input as validator_sanitize

        # Use the validator chain (Chain of Responsibility pattern)
        sanitized, warnings = validator_sanitize(text)

        return sanitized, warnings

    # MongoDB write operations that should be blocked
    MONGODB_WRITE_OPERATIONS = [
        "insertOne",
        "insertMany",
        "insert",
        "updateOne",
        "updateMany",
        "update",
        "replaceOne",
        "deleteOne",
        "deleteMany",
        "delete",
        "remove",
        "drop",
        "createCollection",
        "createIndex",
        "dropIndex",
        "renameCollection",
        "bulkWrite",
        "findOneAndDelete",
        "findOneAndReplace",
        "findOneAndUpdate",
    ]

    # MongoDB read-only operations that are allowed
    MONGODB_READ_OPERATIONS = [
        "find",
        "findOne",
        "aggregate",
        "count",
        "countDocuments",
        "estimatedDocumentCount",
        "distinct",
        "explain",
    ]

    @classmethod
    def validate_generated_sql(
        cls, sql: str, db_type: str = "postgresql"
    ) -> Tuple[bool, str]:
        """
        Validate that generated query is read-only.
        Uses QueryValidatorRegistry (Strategy Pattern) to route to appropriate validator.

        Supported query languages:
        - SQL (PostgreSQL, MySQL, SQL Server, Oracle, Snowflake, BigQuery, etc.): SELECT/WITH only
        - MongoDB: Read operations only (find, aggregate, count, distinct)
        - CQL (Cassandra): SELECT only
        - PartiQL (DynamoDB): SELECT only

        Returns: (is_valid, message)
        """
        if not sql or not sql.strip():
            return False, "Empty query"

        # Import here to avoid circular imports
        from app.services.validators.query_validators import QueryValidatorRegistry

        # Use Strategy Pattern - delegate to appropriate validator
        is_valid, cleaned_query, error_message = QueryValidatorRegistry.validate_query(
            sql, db_type
        )

        if is_valid:
            return True, "Valid read-only query"
        else:
            return False, error_message or "Query validation failed"

    @classmethod
    def _validate_mongodb_query(cls, query: str) -> Tuple[bool, str]:
        """
        Validate MongoDB query is read-only.

        SECURITY: Detects chained operations like:
        - db.users.find({}).deleteMany({})
        - db.collection.aggregate([]).forEach(function(){db.other.drop()})
        """
        query_lower = query.lower()

        # CRITICAL: Check for write operations ANYWHERE in the query
        # This catches chained operations like find().deleteMany()
        for write_op in cls.MONGODB_WRITE_OPERATIONS:
            # Match operation name followed by ( anywhere in query
            # Use word boundary to avoid false positives
            # SECURITY: Escape operation name to prevent regex injection
            escaped_op = re.escape(write_op.lower())
            pattern = rf"\.{escaped_op}\s*\("
            if re.search(pattern, query_lower):
                return False, f"Blocked: {write_op} is a write operation"

            # Also check for operations in strings (potential injection in forEach, etc.)
            pattern_in_string = rf'["\']\.{escaped_op}\s*\('
            if re.search(pattern_in_string, query_lower):
                return False, f"Blocked: {write_op} detected in query string"

        # Check for method chaining patterns that could hide write ops
        # e.g., .forEach(function(){...write op...})
        dangerous_chaining = [
            r"\.foreach\s*\(",  # forEach can execute arbitrary code
            r"\.map\s*\(\s*function",  # map with function
            r"\.toarray\s*\(\s*\)\s*\.",  # toArray().someMethod()
        ]
        for pattern in dangerous_chaining:
            if re.search(pattern, query_lower):
                return (
                    False,
                    "Blocked: Query contains potentially dangerous method chaining",
                )

        # Must contain at least one read operation
        has_read_op = False
        for read_op in cls.MONGODB_READ_OPERATIONS:
            # SECURITY: Escape operation name to prevent regex injection
            escaped_op = re.escape(read_op.lower())
            pattern = rf"\.{escaped_op}\s*\("
            if re.search(pattern, query_lower):
                has_read_op = True
                break

        # Also check for aggregation pipeline format (array starting with $)
        if not has_read_op and "[" in query and "$" in query:
            # Looks like an aggregation pipeline
            has_read_op = True

        if not has_read_op:
            return False, "Query must use a read operation (find, aggregate, etc.)"

        # Check for dangerous patterns (JavaScript injection, etc.)
        dangerous_patterns = [
            (r"\$where", "$where can execute arbitrary JavaScript"),
            (r"function\s*\(", "JavaScript functions not allowed"),
            (r"eval\s*\(", "eval() not allowed"),
            (r"this\.", "this. reference not allowed"),
            (
                r"db\.[a-z]+\.[a-z]+\s*\(.*\)\s*\.\s*[a-z]+\s*\(",
                "Multiple chained operations detected",
            ),
            (r";\s*db\.", "Multiple statements detected"),
        ]
        for pattern, message in dangerous_patterns:
            if re.search(pattern, query_lower):
                return False, f"Blocked: {message}"

        # Additional check: count method calls - if more than expected for read op, suspicious
        method_calls = re.findall(r"\.\w+\s*\(", query_lower)
        if len(method_calls) > 5:  # Reasonable limit for a read query
            # Verify all are safe methods
            safe_methods = [
                "find",
                "findone",
                "aggregate",
                "count",
                "countdocuments",
                "distinct",
                "explain",
                "limit",
                "skip",
                "sort",
                "project",
                "match",
                "group",
                "lookup",
                "unwind",
                "toarray",
            ]
            for call in method_calls:
                # Extract method name: ".methodName(" -> "methodname"
                method_name = call.replace(".", "").replace("(", "").strip()
                if method_name and method_name not in safe_methods:
                    # Check if it's a write operation we might have missed
                    if any(
                        w.lower() in method_name for w in cls.MONGODB_WRITE_OPERATIONS
                    ):
                        return (
                            False,
                            f"Blocked: Suspicious method {method_name} detected",
                        )

        return True, "Valid read-only MongoDB query"

    @classmethod
    def _validate_cql_query(cls, query: str) -> Tuple[bool, str]:
        """
        Validate Cassandra CQL query is read-only.

        CQL is SQL-like but has Cassandra-specific concerns:
        - ALLOW FILTERING should be warned (performance issue, not security)
        - Must be SELECT only
        - Block dangerous operations like DROP, TRUNCATE, etc.
        """
        query_upper = query.upper().strip()

        # Must start with SELECT
        if not query_upper.startswith("SELECT"):
            return False, "CQL query must be a SELECT statement"

        # Block write/DDL operations
        # Includes EXECUTE (arbitrary CQL) and APPLY (conditional batch writes)
        cql_blocked_keywords = [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "TRUNCATE",
            "CREATE",
            "ALTER",
            "GRANT",
            "REVOKE",
            "BATCH",
            "EXECUTE",
            "APPLY",
        ]
        for keyword in cql_blocked_keywords:
            escaped_keyword = re.escape(keyword)
            pattern = rf"(^|\s|;)\s*{escaped_keyword}\s+"
            if re.search(pattern, query_upper):
                return False, f"Blocked: {keyword} operations are not allowed in CQL"

        # Check for multiple statements
        if re.search(r";\s*\w", query):
            return False, "Multiple CQL statements not allowed"

        # Warn about ALLOW FILTERING (performance concern)
        # This is a warning, not a block - let it pass but log
        if "ALLOW FILTERING" in query_upper:
            logger.warning("CQL query uses ALLOW FILTERING - may cause full table scan")

        return True, "Valid read-only CQL query"

    @classmethod
    def _validate_partiql_query(cls, query: str) -> Tuple[bool, str]:
        """
        Validate DynamoDB PartiQL query is read-only.

        PartiQL is SQL-like but specific to DynamoDB:
        - Must be SELECT only
        - Block INSERT, UPDATE, DELETE operations
        - Warn about queries without partition key (causes SCAN)
        """
        query_upper = query.upper().strip()

        # Must start with SELECT
        if not query_upper.startswith("SELECT"):
            return False, "PartiQL query must be a SELECT statement"

        # Block write operations
        partiql_blocked_keywords = [
            "INSERT",
            "UPDATE",
            "DELETE",
        ]
        for keyword in partiql_blocked_keywords:
            escaped_keyword = re.escape(keyword)
            pattern = rf"(^|\s|;)\s*{escaped_keyword}\s+"
            if re.search(pattern, query_upper):
                return (
                    False,
                    f"Blocked: {keyword} operations are not allowed in PartiQL",
                )

        # Check for multiple statements
        if re.search(r";\s*\w", query):
            return False, "Multiple PartiQL statements not allowed"

        # Warn about queries that might cause expensive SCAN operations
        # A query without WHERE clause on a DynamoDB table causes a full SCAN
        if "WHERE" not in query_upper:
            logger.warning(
                "PartiQL query without WHERE clause will perform expensive SCAN operation"
            )

        return True, "Valid read-only PartiQL query"

    @classmethod
    def _validate_sql_query(cls, sql: str) -> Tuple[bool, str]:
        """Validate SQL query is read-only (SELECT only)"""
        sql_upper = sql.upper()

        # Must start with SELECT or WITH (for CTEs)
        if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
            return False, "Query must be a SELECT statement"

        # Check for dangerous keywords that indicate write operations
        for keyword in cls.DANGEROUS_SQL_KEYWORDS:
            # Match keyword at word boundary (not part of column name)
            # SECURITY: Escape keyword to prevent regex injection
            escaped_keyword = re.escape(keyword)
            pattern = rf"(^|\s|;|\()\s*{escaped_keyword}\s+"
            if re.search(pattern, sql_upper):
                return False, f"Blocked: {keyword} statements are not allowed"

        # Check for SQL injection patterns in generated SQL
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, sql, re.IGNORECASE):
                return False, "Query contains suspicious patterns"

        # Check for multiple statements (semicolon followed by keyword)
        if re.search(r";\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE)", sql_upper):
            return False, "Multiple statements not allowed"

        return True, "Valid read-only query"

    @classmethod
    def sanitize_sql_for_execution(cls, sql: str) -> str:
        """
        Final sanitization before execution
        """
        # Remove trailing semicolons and whitespace
        sql = sql.strip().rstrip(";").strip()

        # Remove SQL comments
        sql = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
        sql = re.sub(r"/\*[\s\S]*?\*/", "", sql)

        # Remove any null bytes
        sql = sql.replace("\x00", "")

        return sql.strip()

    @classmethod
    def mask_sensitive_data(cls, text: str) -> str:
        """
        Mask sensitive data in logs
        """
        # Mask passwords in connection strings
        text = re.sub(r"(://[^:]+:)[^@]+(@)", r"\1****\2", text)

        # Mask API keys
        text = re.sub(r"(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9]+", r"\1****", text)
        text = re.sub(
            r'(api[_-]?key["\s:=]+)["\']?[a-zA-Z0-9]+',
            r"\1****",
            text,
            flags=re.IGNORECASE,
        )

        return text

    # =========================================================================
    # DML (Data Modification Language) Support
    # =========================================================================

    # Patterns to detect DML operations
    DML_PATTERNS = {
        "INSERT": r"\bINSERT\s+INTO\b",
        "UPDATE": r"\bUPDATE\b.*\bSET\b",
        "DELETE": r"\bDELETE\s+FROM\b",
        "TRUNCATE": r"\bTRUNCATE\b",
        "DROP": r"\bDROP\b",
        "ALTER": r"\bALTER\b",
        "CREATE": r"\bCREATE\b",
    }

    # Dangerous operations - NEVER allowed even with DML mode
    BLOCKED_DML_OPERATIONS = {"TRUNCATE", "DROP", "ALTER", "CREATE"}

    # Allowed DML operations when DML mode is enabled
    ALLOWED_DML_OPERATIONS = {"INSERT", "UPDATE", "DELETE"}

    # Database-specific DML restrictions
    DB_DML_RESTRICTIONS = {
        "mysql": {
            "blocked_patterns": [
                r"LOAD\s+DATA",  # File system access
                r"INTO\s+OUTFILE",  # File system write
                r"INTO\s+DUMPFILE",  # Binary file write
            ]
        },
        "sqlserver": {
            "blocked_patterns": [
                r"xp_cmdshell",  # Command execution
                r"sp_executesql",  # Dynamic SQL (potential injection)
                r"OPENROWSET",  # External data access
                r"OPENDATASOURCE",  # External data access
            ]
        },
        "oracle": {
            "blocked_patterns": [
                r"UTL_FILE",  # File system access
                r"DBMS_SCHEDULER",  # Job scheduling
                r"DBMS_JOB",  # Job creation
                r"EXECUTE\s+IMMEDIATE",  # Dynamic SQL
            ]
        },
        "clickhouse": {
            "blocked_patterns": [
                r"ALTER\s+TABLE.*DELETE",  # Async deletes
                r"OPTIMIZE\s+TABLE",  # Table optimization
                r"SYSTEM\s+",  # System commands
            ]
        },
        "postgresql": {
            "blocked_patterns": [
                r"COPY\s+.*\s+TO\s+",  # File system write
                r"COPY\s+.*\s+FROM\s+",  # File system read
                r"pg_read_file",  # File system access
                r"pg_write_file",  # File system access
            ]
        },
    }

    # MongoDB-specific blocked operations
    BLOCKED_MONGO_DML_OPS = {
        "drop",
        "dropDatabase",
        "dropCollection",
        "createCollection",
        "createIndex",
        "dropIndex",
        "renameCollection",
        "aggregate",  # aggregate with $out/$merge
    }

    # MongoDB allowed DML operations
    ALLOWED_MONGO_DML_OPS = {
        "insertOne",
        "insertMany",
        "updateOne",
        "updateMany",
        "deleteOne",
        "deleteMany",
    }

    @classmethod
    def detect_dml_operation(cls, sql: str) -> Optional[str]:
        """
        Detect if SQL is a DML operation and return the operation type.

        Args:
            sql: SQL statement to analyze

        Returns:
            Operation type (INSERT, UPDATE, DELETE, etc.) or None if not DML
        """
        sql_upper = sql.upper()
        for op, pattern in cls.DML_PATTERNS.items():
            if re.search(pattern, sql_upper):
                return op
        return None

    @classmethod
    def validate_dml_sql(cls, sql: str, dml_mode: str) -> Tuple[bool, str]:
        """
        Validate DML statement based on the DML mode.

        DML Modes:
        - disabled: No DML allowed (default, read-only)
        - preview: DML allowed for preview (generates SELECT instead)
        - sandbox: DML allowed (will be rolled back)
        - confirm: DML allowed with confirmation token

        Args:
            sql: SQL statement to validate
            dml_mode: One of 'disabled', 'preview', 'sandbox', 'confirm'

        Returns:
            (is_valid, message) tuple
        """
        if not sql or not sql.strip():
            return False, "Empty SQL statement"

        operation = cls.detect_dml_operation(sql)

        # Not a DML operation - valid for any mode
        if not operation:
            return True, "OK"

        # Always block dangerous operations (DROP, TRUNCATE, ALTER, CREATE)
        if operation in cls.BLOCKED_DML_OPERATIONS:
            return False, f"{operation} operations are not allowed for safety reasons"

        # Check if DML is enabled
        if dml_mode == "disabled":
            return (
                False,
                f"{operation} operations require DML mode to be enabled. Enable preview, sandbox, or confirm mode.",
            )

        # For UPDATE and DELETE, require WHERE clause to prevent accidental mass operations
        if operation in ("UPDATE", "DELETE"):
            sql_upper = sql.upper()
            if "WHERE" not in sql_upper:
                return (
                    False,
                    f"{operation} without WHERE clause is not allowed - this would affect all rows",
                )

            # Additional safety: check for always-true conditions
            always_true_patterns = [
                r"WHERE\s+1\s*=\s*1",
                r"WHERE\s+TRUE",
                r"WHERE\s+\'1\'\s*=\s*\'1\'",
            ]
            for pattern in always_true_patterns:
                if re.search(pattern, sql_upper):
                    return (
                        False,
                        f"{operation} with always-true WHERE clause is not allowed",
                    )

        # Check for SQL injection patterns in DML
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, sql, re.IGNORECASE):
                return False, "SQL statement contains suspicious patterns"

        # Check for multiple statements
        if re.search(r";\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE)", sql.upper()):
            return False, "Multiple statements not allowed"

        return True, "OK"

    @classmethod
    def get_dml_preview_sql(cls, sql: str) -> Optional[str]:
        """
        Convert a DML statement to a SELECT statement for preview.

        This shows what rows would be affected without making changes.

        Args:
            sql: DML statement (UPDATE or DELETE)

        Returns:
            SELECT statement that shows affected rows, or None if not applicable
        """
        operation = cls.detect_dml_operation(sql)

        if operation == "DELETE":
            # DELETE FROM table WHERE condition -> SELECT * FROM table WHERE condition
            preview = re.sub(
                r"\bDELETE\s+FROM\b", "SELECT * FROM", sql, flags=re.IGNORECASE
            )
            return preview

        elif operation == "UPDATE":
            # UPDATE table SET ... WHERE condition -> SELECT * FROM table WHERE condition
            # Extract table name and WHERE clause
            # Pattern handles: simple (users), schema-qualified (public.users), quoted ("User Table")
            match = re.search(
                r'UPDATE\s+((?:[\w]+\.)?(?:[\w]+|"[^"]+"))\s+SET\s+.*?(WHERE\s+.+)?$',
                sql,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                table = match.group(1)
                where_clause = match.group(2) or ""
                return f"SELECT * FROM {table} {where_clause}".strip()

        elif operation == "INSERT":
            # For INSERT, we can't really preview - return None
            return None

        return None

    @classmethod
    def validate_dml_for_database(cls, sql: str, db_type: str) -> Tuple[bool, str]:
        """
        Validate DML statement against database-specific restrictions.

        Different databases have different security concerns:
        - MySQL: File system access via LOAD DATA/OUTFILE
        - SQL Server: xp_cmdshell, sp_executesql
        - Oracle: UTL_FILE, DBMS_SCHEDULER
        - PostgreSQL: COPY, file functions
        - ClickHouse: ALTER TABLE DELETE, OPTIMIZE

        Args:
            sql: SQL statement to validate
            db_type: Database type (mysql, postgresql, etc.)

        Returns:
            (is_valid, message) tuple
        """
        restrictions = cls.DB_DML_RESTRICTIONS.get(db_type.lower(), {})
        blocked_patterns = restrictions.get("blocked_patterns", [])

        for pattern in blocked_patterns:
            if re.search(pattern, sql, re.IGNORECASE):
                logger.warning(
                    "DB-specific DML restriction triggered",
                    db_type=db_type,
                    pattern=pattern[:30],
                )
                return (
                    False,
                    f"Operation not allowed on {db_type}: matches restricted pattern",
                )

        return True, "OK"

    @classmethod
    def validate_mongo_dml(cls, query: str) -> Tuple[bool, str]:
        """
        Validate MongoDB DML (mutation) operation.

        Checks:
        - Operation is in allowed list (insertOne, updateOne, deleteOne, etc.)
        - Operation is NOT in blocked list (drop, createIndex, etc.)
        - For update/delete: filter is not empty {}
        - No dangerous patterns ($where, JavaScript, etc.)

        Args:
            query: MongoDB query string

        Returns:
            (is_valid, message) tuple
        """
        query_lower = query.lower()

        # Block dangerous operations
        for blocked in cls.BLOCKED_MONGO_DML_OPS:
            escaped_op = re.escape(blocked.lower())
            pattern = rf"\.{escaped_op}\s*\("
            if re.search(pattern, query_lower):
                return False, f"{blocked} operation is not allowed"

        # Check for allowed operations
        has_allowed_op = False
        operation_found = None
        for allowed in cls.ALLOWED_MONGO_DML_OPS:
            escaped_op = re.escape(allowed.lower())
            pattern = rf"\.{escaped_op}\s*\("
            if re.search(pattern, query_lower):
                has_allowed_op = True
                operation_found = allowed
                break

        if not has_allowed_op:
            return (
                False,
                f"Operation not recognized. Allowed: {', '.join(cls.ALLOWED_MONGO_DML_OPS)}",
            )

        # For update/delete: require non-empty filter
        if operation_found and operation_found.lower() in (
            "updateone",
            "updatemany",
            "deleteone",
            "deletemany",
        ):
            # Check for empty filter {} as first argument
            empty_filter_pattern = (
                rf"\.{re.escape(operation_found.lower())}\s*\(\s*\{{\s*\}}\s*[,)]"
            )
            if re.search(empty_filter_pattern, query_lower):
                return (
                    False,
                    f"Empty filter {{}} not allowed for {operation_found} - this would affect all documents",
                )

        # Check for dangerous patterns
        dangerous_patterns = [
            (r"\$where", "$where can execute arbitrary JavaScript"),
            (r"function\s*\(", "JavaScript functions not allowed in DML"),
            (r"eval\s*\(", "eval() not allowed"),
            (r";\s*db\.", "Multiple statements not allowed"),
        ]
        for pattern, message in dangerous_patterns:
            if re.search(pattern, query_lower):
                return False, f"Blocked: {message}"

        # Check for $out or $merge in aggregate (these write data)
        if "aggregate" in query_lower:
            if re.search(r"\$out\s*:", query_lower) or re.search(
                r"\$merge\s*:", query_lower
            ):
                return (
                    False,
                    "aggregate with $out or $merge is not allowed - use insertMany instead",
                )

        return True, "OK"

    @classmethod
    def detect_mongo_dml_operation(cls, query: str) -> Optional[str]:
        """
        Detect MongoDB DML operation type.

        Args:
            query: MongoDB query string

        Returns:
            Operation name (insertOne, updateOne, etc.) or None
        """
        query_lower = query.lower()

        all_ops = list(cls.ALLOWED_MONGO_DML_OPS) + list(cls.BLOCKED_MONGO_DML_OPS)
        for op in all_ops:
            escaped_op = re.escape(op.lower())
            pattern = rf"\.{escaped_op}\s*\("
            if re.search(pattern, query_lower):
                return op

        return None
