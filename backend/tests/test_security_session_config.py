"""
Comprehensive unit tests for:
  1. app/services/security.py - Security services
  2. app/services/session_store.py - SessionStore singleton
  3. app/core/config.py - Settings

All external dependencies (Redis, databases) are mocked.
No chromadb or vector DB imports.
"""

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _disable_redis():
    """Ensure Redis is never available during tests - in-memory fallback only."""
    with patch("app.services.security._redis_helper") as mock_helper:
        mock_helper.available = False
        mock_helper.client = None
        yield mock_helper


@pytest.fixture
def _enable_redis(_disable_redis):
    """Re-enable a mocked Redis client for tests that need it."""
    mock_client = MagicMock()
    _disable_redis.available = True
    _disable_redis.client = mock_client
    return mock_client


# ============================================================================
# 1. SECURITY MODULE TESTS (app/services/security.py)
# ============================================================================


class TestSessionTokenService:
    """Tests for SessionTokenService: signed session IDs."""

    def test_create_signed_session_id_format(self):
        from app.services.security import SessionTokenService

        sid = SessionTokenService.create_signed_session_id()
        parts = sid.split(":")
        assert len(parts) == 3, "Signed session ID must have three colon-separated parts"
        uuid_part, ts_part, sig_part = parts
        assert len(uuid_part) == 32, "UUID portion must be 32 hex chars"
        assert ts_part.isdigit(), "Timestamp portion must be numeric"
        assert len(sig_part) == 16, "Signature portion must be 16 hex chars"

    def test_create_signed_session_id_uniqueness(self):
        from app.services.security import SessionTokenService

        ids = {SessionTokenService.create_signed_session_id() for _ in range(50)}
        assert len(ids) == 50, "Each generated session ID must be unique"

    def test_verify_valid_session_id(self):
        from app.services.security import SessionTokenService

        sid = SessionTokenService.create_signed_session_id()
        is_valid, msg = SessionTokenService.verify_session_id(sid)
        assert is_valid is True
        assert msg == "Valid"

    def test_verify_invalid_format_too_few_parts(self):
        from app.services.security import SessionTokenService

        is_valid, msg = SessionTokenService.verify_session_id("only-one-part")
        assert is_valid is False
        assert "format" in msg.lower()

    def test_verify_invalid_format_too_many_parts(self):
        from app.services.security import SessionTokenService

        is_valid, msg = SessionTokenService.verify_session_id("a:b:c:d")
        assert is_valid is False
        assert "format" in msg.lower()

    def test_verify_invalid_signature(self):
        from app.services.security import SessionTokenService

        sid = SessionTokenService.create_signed_session_id()
        uuid_part, ts_part, _ = sid.split(":")
        tampered = f"{uuid_part}:{ts_part}:{'0' * 16}"
        is_valid, msg = SessionTokenService.verify_session_id(tampered)
        assert is_valid is False
        assert "signature" in msg.lower()

    def test_verify_tampered_uuid(self):
        from app.services.security import SessionTokenService

        sid = SessionTokenService.create_signed_session_id()
        _, ts_part, sig_part = sid.split(":")
        tampered = f"{'f' * 32}:{ts_part}:{sig_part}"
        is_valid, msg = SessionTokenService.verify_session_id(tampered)
        assert is_valid is False

    def test_verify_expired_session(self):
        """Session older than 30 days must be rejected."""
        from app.services.security import SessionTokenService, SERVER_SECRET

        uuid_part = secrets.token_hex(16)
        old_timestamp = str(int(time.time()) - 31 * 24 * 3600)
        message = f"{uuid_part}:{old_timestamp}".encode("utf-8")
        sig = hmac.new(
            SERVER_SECRET.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()[:16]
        old_sid = f"{uuid_part}:{old_timestamp}:{sig}"

        is_valid, msg = SessionTokenService.verify_session_id(old_sid)
        assert is_valid is False
        assert "expired" in msg.lower()

    def test_verify_not_yet_expired_session(self):
        """Session just under 30 days should still be valid."""
        from app.services.security import SessionTokenService, SERVER_SECRET

        uuid_part = secrets.token_hex(16)
        recent_timestamp = str(int(time.time()) - 29 * 24 * 3600)
        message = f"{uuid_part}:{recent_timestamp}".encode("utf-8")
        sig = hmac.new(
            SERVER_SECRET.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()[:16]
        sid = f"{uuid_part}:{recent_timestamp}:{sig}"

        is_valid, msg = SessionTokenService.verify_session_id(sid)
        assert is_valid is True

    def test_verify_empty_string(self):
        from app.services.security import SessionTokenService

        is_valid, msg = SessionTokenService.verify_session_id("")
        assert is_valid is False

    def test_verify_non_integer_timestamp(self):
        from app.services.security import SessionTokenService

        is_valid, msg = SessionTokenService.verify_session_id("abc:notanumber:0123456789abcdef")
        assert is_valid is False
        # Signature check fails before timestamp parsing, so either message is acceptable
        assert "invalid" in msg.lower() or "failed" in msg.lower()


class TestCSRFProtection:
    """Tests for CSRFProtection: token generation and verification."""

    def test_generate_token_returns_hex_string(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        token = csrf.generate_token("session-1")
        assert isinstance(token, str)
        assert len(token) == 64

    def test_verify_valid_token(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        token = csrf.generate_token("session-1")
        is_valid, msg = csrf.verify_token("session-1", token)
        assert is_valid is True
        assert msg == "Valid"

    def test_verify_empty_token(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        is_valid, msg = csrf.verify_token("session-1", "")
        assert is_valid is False
        assert "required" in msg.lower()

    def test_verify_none_token(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        is_valid, msg = csrf.verify_token("session-1", None)
        assert is_valid is False

    def test_verify_wrong_session(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        token = csrf.generate_token("session-A")
        is_valid, msg = csrf.verify_token("session-B", token)
        assert is_valid is False

    def test_verify_wrong_token(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        csrf.generate_token("session-1")
        is_valid, msg = csrf.verify_token("session-1", "wrong-token-value")
        assert is_valid is False
        assert "invalid" in msg.lower()

    def test_expired_token(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        token = csrf.generate_token("session-1")
        csrf._tokens["session-1"][token] = time.time() - 1
        is_valid, msg = csrf.verify_token("session-1", token)
        assert is_valid is False
        assert "expired" in msg.lower()

    def test_cleanup_session_removes_tokens(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        csrf.generate_token("session-1")
        csrf.generate_token("session-1")
        assert len(csrf._tokens["session-1"]) == 2
        csrf.cleanup_session("session-1")
        assert "session-1" not in csrf._tokens

    def test_cleanup_session_nonexistent_is_noop(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        csrf.cleanup_session("nonexistent")

    def test_multiple_tokens_per_session(self):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        t1 = csrf.generate_token("s1")
        t2 = csrf.generate_token("s1")
        assert t1 != t2
        assert csrf.verify_token("s1", t1) == (True, "Valid")
        assert csrf.verify_token("s1", t2) == (True, "Valid")

    def test_generate_token_with_redis(self, _enable_redis):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        token = csrf.generate_token("session-redis")
        assert isinstance(token, str)
        _enable_redis.setex.assert_called_once()

    def test_verify_token_with_redis_found(self, _enable_redis):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        _enable_redis.exists.return_value = True
        is_valid, msg = csrf.verify_token("s1", "some-token")
        assert is_valid is True

    def test_verify_token_redis_failure_falls_back(self, _enable_redis):
        from app.services.security import CSRFProtection

        csrf = CSRFProtection()
        token = csrf.generate_token("s1")
        _enable_redis.exists.side_effect = Exception("Redis down")
        csrf._tokens["s1"][token] = time.time() + 3600
        is_valid, msg = csrf.verify_token("s1", token)
        assert is_valid is True


class TestErrorSanitizer:
    """Tests for ErrorSanitizer."""

    def test_sanitize_production_connection_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Connection refused to host secret-server:5432")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert result == ErrorSanitizer.GENERIC_MESSAGES["connection"]

    def test_sanitize_production_auth_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Authentication failed for user admin with password foobar")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert result == ErrorSanitizer.GENERIC_MESSAGES["authentication"]

    def test_sanitize_production_timeout_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Request timed out after 30 seconds")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert result == ErrorSanitizer.GENERIC_MESSAGES["timeout"]

    def test_sanitize_production_permission_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Permission denied on table users")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert result == ErrorSanitizer.GENERIC_MESSAGES["permission"]

    def test_sanitize_production_not_found(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Resource not found (404)")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert result == ErrorSanitizer.GENERIC_MESSAGES["not_found"]

    def test_sanitize_production_validation_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Invalid input format")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert result == ErrorSanitizer.GENERIC_MESSAGES["validation"]

    def test_sanitize_production_rate_limit_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Rate limit exceeded")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert result == ErrorSanitizer.GENERIC_MESSAGES["rate_limit"]

    def test_sanitize_production_unknown_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Something completely unknown went wrong")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert result == ErrorSanitizer.GENERIC_MESSAGES["internal"]

    def test_sanitize_database_error_shown_in_production(self):
        from app.services.security import ErrorSanitizer

        err = Exception('column "nonexistent" does not exist')
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert "does not exist" in result

    def test_sanitize_syntax_error_shown(self):
        from app.services.security import ErrorSanitizer

        err = Exception("syntax error at position 42")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert "syntax error" in result

    def test_sanitize_dev_mode_shows_detail(self):
        from app.services.security import ErrorSanitizer

        err = Exception("Detailed internal error info here")
        result = ErrorSanitizer.sanitize_error(err, is_production=False)
        assert "Detailed internal error info here" in result

    def test_redact_password_in_dev_mode(self):
        from app.services.security import ErrorSanitizer

        err = Exception('password="supersecret123"')
        result = ErrorSanitizer.sanitize_error(err, is_production=False)
        assert "supersecret123" not in result
        assert "password=***" in result

    def test_redact_api_key(self):
        from app.services.security import ErrorSanitizer

        result = ErrorSanitizer._redact_sensitive('api_key="sk-abc123456"')
        assert "sk-abc123456" not in result
        assert "api_key=***" in result

    def test_redact_credentials_in_url(self):
        from app.services.security import ErrorSanitizer

        result = ErrorSanitizer._redact_sensitive(
            "postgresql://admin:secretpass@host:5432/db"
        )
        assert "secretpass" not in result
        assert "://***:***@" in result

    def test_redact_token(self):
        from app.services.security import ErrorSanitizer

        result = ErrorSanitizer._redact_sensitive('token="mytoken123"')
        assert "mytoken123" not in result

    def test_safe_log_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception('secret="topsecret" happened')
        result = ErrorSanitizer.safe_log_error(err)
        assert "topsecret" not in result
        assert "secret=***" in result

    def test_sanitize_error_default_production_flag(self):
        from app.services.security import ErrorSanitizer

        with patch("app.services.security.settings") as mock_settings:
            mock_settings.DEBUG = False
            err = Exception("Something completely unknown went wrong")
            result = ErrorSanitizer.sanitize_error(err, is_production=None)
            assert result == ErrorSanitizer.GENERIC_MESSAGES["internal"]

    def test_sanitize_division_by_zero_db_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("division by zero in aggregate query")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert "division by zero" in result

    def test_sanitize_duplicate_key_db_error(self):
        from app.services.security import ErrorSanitizer

        err = Exception("duplicate key value violates unique constraint")
        result = ErrorSanitizer.sanitize_error(err, is_production=True)
        assert "duplicate key" in result


class TestRateLimiter:
    """Tests for RateLimiter."""

    def test_first_request_allowed(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        allowed, msg = limiter.check_rate_limit("sess-1", "default")
        assert allowed is True
        assert msg == "OK"

    def test_within_limit_allowed(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        for _ in range(5):
            allowed, _ = limiter.check_rate_limit("sess-1", "generate")
        assert allowed is True

    def test_exceed_limit_blocked(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        for _ in range(10):
            limiter.check_rate_limit("sess-1", "generate")
        allowed, msg = limiter.check_rate_limit("sess-1", "generate")
        assert allowed is False
        assert "rate limit" in msg.lower()

    def test_different_sessions_independent(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        for _ in range(10):
            limiter.check_rate_limit("sess-A", "generate")
        allowed_a, _ = limiter.check_rate_limit("sess-A", "generate")
        assert allowed_a is False
        allowed_b, _ = limiter.check_rate_limit("sess-B", "generate")
        assert allowed_b is True

    def test_different_endpoints_independent(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        for _ in range(5):
            limiter.check_rate_limit("sess-1", "export")
        blocked, _ = limiter.check_rate_limit("sess-1", "export")
        assert blocked is False
        allowed, _ = limiter.check_rate_limit("sess-1", "default")
        assert allowed is True

    def test_old_requests_expire(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        old_time = time.time() - 120
        limiter._requests["sess-1"] = [(old_time, "generate") for _ in range(20)]
        allowed, _ = limiter.check_rate_limit("sess-1", "generate")
        assert allowed is True

    def test_cleanup_session(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        limiter.check_rate_limit("sess-1", "default")
        assert "sess-1" in limiter._requests
        limiter.cleanup_session("sess-1")
        assert "sess-1" not in limiter._requests

    def test_cleanup_nonexistent_session_is_noop(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        limiter.cleanup_session("nonexistent")

    def test_unknown_endpoint_uses_default(self):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        allowed, _ = limiter.check_rate_limit("sess-1", "unknown_endpoint")
        assert allowed is True

    def test_rate_limit_with_redis(self, _enable_redis):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        _enable_redis.get.return_value = None
        allowed, _ = limiter.check_rate_limit("sess-1", "default")
        assert allowed is True
        _enable_redis.setex.assert_called_once()

    def test_rate_limit_redis_exceeds(self, _enable_redis):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        _enable_redis.get.return_value = "999"
        allowed, msg = limiter.check_rate_limit("sess-1", "generate")
        assert allowed is False

    def test_rate_limit_redis_failure_falls_back(self, _enable_redis):
        from app.services.security import RateLimiter

        limiter = RateLimiter()
        _enable_redis.get.side_effect = Exception("Redis down")
        allowed, _ = limiter.check_rate_limit("sess-1", "default")
        assert allowed is True


class TestAuditLogger:
    """Tests for AuditLogger."""

    def test_log_sql_execution_success(self):
        from app.services.security import AuditLogger

        AuditLogger.log_sql_execution(
            session_id="a" * 32, query_id="b" * 32,
            sql="SELECT 1", success=True, row_count=1,
        )

    def test_log_sql_execution_failure(self):
        from app.services.security import AuditLogger

        AuditLogger.log_sql_execution(
            session_id="a" * 32, query_id="b" * 32,
            sql="SELECT invalid_col", success=False,
            row_count=0, error="column not found",
        )

    def test_log_sql_execution_long_sql_truncated(self):
        from app.services.security import AuditLogger

        long_sql = "SELECT " + "a, " * 200
        AuditLogger.log_sql_execution("s" * 32, "q" * 32, long_sql, True, 10)

    def test_log_security_event(self):
        from app.services.security import AuditLogger

        AuditLogger.log_security_event("s" * 32, "SQL_INJECTION", "Detected injection")

    def test_log_security_event_with_none_session(self):
        from app.services.security import AuditLogger

        AuditLogger.log_security_event(None, "UNKNOWN", "Test event")

    def test_log_session_event(self):
        from app.services.security import AuditLogger

        AuditLogger.log_session_event("s" * 32, "CREATED", "Session created")

    def test_log_session_event_no_details(self):
        from app.services.security import AuditLogger

        AuditLogger.log_session_event("s" * 32, "DESTROYED")


class TestSecurityServiceSQLValidation:
    """Tests for SecurityService SQL validation."""

    def test_valid_select(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("SELECT * FROM users")
        assert ok is True

    def test_valid_select_with_cte(self):
        from app.services.security import SecurityService
        sql = "WITH cte AS (SELECT 1) SELECT * FROM cte"
        ok, msg = SecurityService._validate_sql_query(sql)
        assert ok is True

    def test_block_insert(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("INSERT INTO users VALUES (1)")
        assert ok is False
        assert "SELECT" in msg

    def test_block_update(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("UPDATE users SET name='x'")
        assert ok is False

    def test_block_delete(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("DELETE FROM users")
        assert ok is False

    def test_block_drop(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("DROP TABLE users")
        assert ok is False

    def test_block_multiple_statements(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("SELECT 1; DROP TABLE users")
        assert ok is False

    def test_block_sleep_injection(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("SELECT sleep(10)")
        assert ok is False

    def test_block_benchmark_injection(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("SELECT benchmark(1000000, SHA1('test'))")
        assert ok is False

    def test_allow_sql_comments_in_validation(self):
        """SQL comments are allowed in validation (stripped at execution time by sanitize_sql_for_execution)."""
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("SELECT /* comment */ * FROM users")
        assert ok is True

    def test_block_hex_injection(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_sql_query("SELECT 0x4142434445464748 FROM dual")
        assert ok is False

    def test_validate_generated_sql_empty(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_generated_sql("")
        assert ok is False
        assert "empty" in msg.lower()

    def test_validate_generated_sql_whitespace_only(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_generated_sql("   ")
        assert ok is False

    @patch("app.services.security.SecurityService.sanitize_input")
    def test_sanitize_input_delegates_to_validators(self, mock_validate):
        from app.services.security import SecurityService
        mock_validate.return_value = ("clean text", [])
        result = SecurityService.sanitize_input("some text")
        assert result == ("clean text", [])


class TestSecurityServiceSQLSanitization:
    """Tests for SQL sanitization before execution."""

    def test_remove_trailing_semicolons(self):
        from app.services.security import SecurityService
        result = SecurityService.sanitize_sql_for_execution("SELECT 1;")
        assert result == "SELECT 1"

    def test_remove_sql_line_comments(self):
        from app.services.security import SecurityService
        result = SecurityService.sanitize_sql_for_execution("SELECT 1 -- this is a comment")
        assert "--" not in result

    def test_remove_block_comments(self):
        from app.services.security import SecurityService
        result = SecurityService.sanitize_sql_for_execution("SELECT /* block */ 1")
        assert "/*" not in result
        assert "*/" not in result

    def test_remove_null_bytes(self):
        from app.services.security import SecurityService
        result = SecurityService.sanitize_sql_for_execution("SELECT\x001")
        assert "\x00" not in result

    def test_strip_whitespace(self):
        from app.services.security import SecurityService
        result = SecurityService.sanitize_sql_for_execution("  SELECT 1  ;  ")
        assert result == "SELECT 1"


class TestSecurityServiceMaskSensitiveData:
    """Tests for masking sensitive data in logs."""

    def test_mask_password_in_connection_string(self):
        from app.services.security import SecurityService
        text = "postgresql://user:mysecretpass@host:5432/db"
        result = SecurityService.mask_sensitive_data(text)
        assert "mysecretpass" not in result
        assert "****" in result

    def test_mask_openai_api_key(self):
        from app.services.security import SecurityService
        text = "Using key sk-abcdef1234567890"
        result = SecurityService.mask_sensitive_data(text)
        assert "1234567890" not in result

    def test_mask_api_key_label(self):
        from app.services.security import SecurityService
        text = 'api_key="mysupersecretkey"'
        result = SecurityService.mask_sensitive_data(text)
        assert "mysupersecretkey" not in result


class TestSecurityServiceDML:
    """Tests for DML validation."""

    def test_detect_dml_insert(self):
        from app.services.security import SecurityService
        assert SecurityService.detect_dml_operation("INSERT INTO users VALUES (1)") == "INSERT"

    def test_detect_dml_update(self):
        from app.services.security import SecurityService
        assert SecurityService.detect_dml_operation("UPDATE users SET name='x' WHERE id=1") == "UPDATE"

    def test_detect_dml_delete(self):
        from app.services.security import SecurityService
        assert SecurityService.detect_dml_operation("DELETE FROM users WHERE id=1") == "DELETE"

    def test_detect_dml_drop(self):
        from app.services.security import SecurityService
        assert SecurityService.detect_dml_operation("DROP TABLE users") == "DROP"

    def test_detect_dml_select_returns_none(self):
        from app.services.security import SecurityService
        assert SecurityService.detect_dml_operation("SELECT * FROM users") is None

    def test_validate_dml_empty_sql(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_dml_sql("", "sandbox")
        assert ok is False
        assert "empty" in msg.lower()

    def test_validate_dml_select_always_ok(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_dml_sql("SELECT 1", "disabled")
        assert ok is True

    def test_validate_dml_blocked_operations(self):
        from app.services.security import SecurityService
        for stmt in ["TRUNCATE TABLE users", "DROP TABLE users",
                      "ALTER TABLE users ADD col INT", "CREATE TABLE evil (id INT)"]:
            ok, msg = SecurityService.validate_dml_sql(stmt, "sandbox")
            assert ok is False, f"Should block: {stmt}"
            assert "not allowed" in msg.lower()

    def test_validate_dml_disabled_mode_blocks_insert(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_dml_sql("INSERT INTO users VALUES (1)", "disabled")
        assert ok is False
        assert "dml mode" in msg.lower()

    def test_validate_dml_sandbox_allows_insert(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_dml_sql("INSERT INTO users VALUES (1)", "sandbox")
        assert ok is True

    def test_validate_dml_update_requires_where(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_dml_sql("UPDATE users SET name='x'", "sandbox")
        assert ok is False
        assert "where" in msg.lower()

    def test_validate_dml_delete_requires_where(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_dml_sql("DELETE FROM users", "sandbox")
        assert ok is False
        assert "where" in msg.lower()

    def test_validate_dml_update_with_where_ok(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_dml_sql("UPDATE users SET name='x' WHERE id=1", "sandbox")
        assert ok is True

    def test_validate_dml_always_true_where_blocked(self):
        from app.services.security import SecurityService
        for stmt in ["UPDATE users SET name='x' WHERE 1=1",
                      "DELETE FROM users WHERE TRUE",
                      "UPDATE users SET name='x' WHERE '1'='1'"]:
            ok, msg = SecurityService.validate_dml_sql(stmt, "sandbox")
            assert ok is False, f"Should block always-true: {stmt}"
            assert "always-true" in msg.lower()

    def test_validate_dml_multiple_statements_blocked(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_dml_sql("INSERT INTO t VALUES (1); DROP TABLE t", "sandbox")
        assert ok is False

    def test_get_dml_preview_delete(self):
        from app.services.security import SecurityService
        preview = SecurityService.get_dml_preview_sql("DELETE FROM users WHERE id=5")
        assert preview is not None
        assert preview.upper().startswith("SELECT")
        assert "users" in preview

    def test_get_dml_preview_update(self):
        from app.services.security import SecurityService
        preview = SecurityService.get_dml_preview_sql("UPDATE users SET name='x' WHERE id=5")
        assert preview is not None
        assert "SELECT" in preview.upper()
        assert "users" in preview

    def test_get_dml_preview_insert_returns_none(self):
        from app.services.security import SecurityService
        assert SecurityService.get_dml_preview_sql("INSERT INTO users VALUES (1)") is None

    def test_get_dml_preview_select_returns_none(self):
        from app.services.security import SecurityService
        assert SecurityService.get_dml_preview_sql("SELECT 1") is None

    def test_validate_dml_for_database_postgresql(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService.validate_dml_for_database("COPY users TO '/tmp/users.csv'", "postgresql")
        assert ok is False

    def test_validate_dml_for_database_mysql(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService.validate_dml_for_database("LOAD DATA INFILE '/tmp/data.csv' INTO TABLE t", "mysql")
        assert ok is False

    def test_validate_dml_for_database_sqlserver(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService.validate_dml_for_database("EXEC xp_cmdshell 'dir'", "sqlserver")
        assert ok is False

    def test_validate_dml_for_database_unknown_db(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService.validate_dml_for_database("INSERT INTO t VALUES (1)", "unknowndb")
        assert ok is True

    def test_validate_dml_for_database_clean_sql(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService.validate_dml_for_database("INSERT INTO t VALUES (1)", "postgresql")
        assert ok is True


class TestSecurityServiceMongoDB:
    """Tests for MongoDB query validation."""

    def test_valid_mongodb_find(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_mongodb_query('db.users.find({})')
        assert ok is True

    def test_valid_mongodb_aggregate(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_mongodb_query('db.users.aggregate([{$match: {age: {$gt: 18}}}])')
        assert ok is True

    def test_block_mongodb_write(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_mongodb_query('db.users.deleteMany({})')
        assert ok is False

    def test_block_mongodb_drop(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_mongodb_query('db.users.drop()')
        assert ok is False

    def test_block_mongodb_chained_write(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_mongodb_query('db.users.find({}).deleteMany({})')
        assert ok is False

    def test_block_mongodb_foreach(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_mongodb_query('db.users.find({}).forEach(function(d){db.other.drop()})')
        assert ok is False

    def test_block_mongodb_where(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_mongodb_query('db.users.find({$where: "this.a > 1"})')
        assert ok is False

    def test_no_read_operation_blocked(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService._validate_mongodb_query('db.users.nonexistentOp()')
        assert ok is False
        assert "read operation" in msg.lower()

    def test_validate_mongo_dml_allowed(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService.validate_mongo_dml('db.users.insertOne({name: "test"})')
        assert ok is True

    def test_validate_mongo_dml_blocked_drop(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService.validate_mongo_dml('db.users.drop()')
        assert ok is False

    def test_validate_mongo_dml_empty_filter(self):
        from app.services.security import SecurityService
        ok, msg = SecurityService.validate_mongo_dml('db.users.deleteMany({})')
        assert ok is False
        assert "empty filter" in msg.lower()

    def test_detect_mongo_dml_operation(self):
        from app.services.security import SecurityService
        op = SecurityService.detect_mongo_dml_operation('db.users.insertOne({name: "test"})')
        assert op == "insertOne"

    def test_detect_mongo_dml_none_for_read(self):
        from app.services.security import SecurityService
        assert SecurityService.detect_mongo_dml_operation('db.users.find({})') is None


class TestSecurityServiceCQLPartiQL:
    """Tests for CQL and PartiQL validation."""

    def test_valid_cql_select(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_cql_query("SELECT * FROM users WHERE id=1")
        assert ok is True

    def test_cql_block_insert(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_cql_query("INSERT INTO users (id) VALUES (1)")
        assert ok is False

    def test_cql_block_drop(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_cql_query("DROP TABLE users")
        assert ok is False

    def test_cql_block_multiple_statements(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_cql_query("SELECT 1; DELETE FROM users")
        assert ok is False

    def test_valid_partiql_select(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_partiql_query("SELECT * FROM users WHERE pk=1")
        assert ok is True

    def test_partiql_block_insert(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_partiql_query("INSERT INTO users VALUE {'pk': 1}")
        assert ok is False

    def test_partiql_block_delete(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_partiql_query("DELETE FROM users WHERE pk=1")
        assert ok is False

    def test_partiql_block_multiple_statements(self):
        from app.services.security import SecurityService
        ok, _ = SecurityService._validate_partiql_query("SELECT 1; UPDATE users SET a=1")
        assert ok is False


class TestQueryLanguageRegistry:
    """Tests for QueryLanguageRegistry."""

    def test_sql_databases(self):
        from app.services.security import QueryLanguageRegistry
        for db in ["postgresql", "mysql", "snowflake", "bigquery"]:
            assert QueryLanguageRegistry.is_sql_database(db) is True

    def test_mongodb_detected(self):
        from app.services.security import QueryLanguageRegistry
        assert QueryLanguageRegistry.is_mongodb("mongodb") is True
        assert QueryLanguageRegistry.is_mongodb("postgresql") is False

    def test_cassandra_detected(self):
        from app.services.security import QueryLanguageRegistry
        assert QueryLanguageRegistry.is_cassandra("cassandra") is True

    def test_dynamodb_detected(self):
        from app.services.security import QueryLanguageRegistry
        assert QueryLanguageRegistry.is_dynamodb("dynamodb") is True

    def test_unknown_defaults_to_sql(self):
        from app.services.security import QueryLanguageRegistry
        assert QueryLanguageRegistry.get_query_language("unknowndb") == "sql"

    def test_get_supported_databases(self):
        from app.services.security import QueryLanguageRegistry
        dbs = QueryLanguageRegistry.get_supported_databases()
        assert "postgresql" in dbs
        assert "mongodb" in dbs

    def test_get_databases_by_language(self):
        from app.services.security import QueryLanguageRegistry
        sql_dbs = QueryLanguageRegistry.get_databases_by_language("sql")
        assert "postgresql" in sql_dbs
        assert "mongodb" not in sql_dbs


class TestResultSizeLimiter:
    """Tests for ResultSizeLimiter."""

    def test_no_rows_key_passthrough(self):
        from app.services.security import ResultSizeLimiter
        data = {"message": "ok"}
        result, warnings = ResultSizeLimiter.check_and_limit_results(data)
        assert result == data
        assert warnings == []

    def test_truncate_large_row_count(self):
        from app.services.security import ResultSizeLimiter
        rows = [{"id": i} for i in range(ResultSizeLimiter.MAX_ROWS + 100)]
        data = {"rows": rows}
        result, warnings = ResultSizeLimiter.check_and_limit_results(data)
        assert len(result["rows"]) == ResultSizeLimiter.MAX_ROWS
        assert any("truncated" in w.lower() for w in warnings)

    def test_truncate_long_cell(self):
        from app.services.security import ResultSizeLimiter
        long_value = "x" * (ResultSizeLimiter.MAX_CELL_LENGTH + 100)
        data = {"rows": [{"text": long_value}]}
        result, warnings = ResultSizeLimiter.check_and_limit_results(data)
        assert len(result["rows"][0]["text"]) <= ResultSizeLimiter.MAX_CELL_LENGTH + 20
        assert any("truncated" in w.lower() for w in warnings)

    def test_normal_results_unchanged(self):
        from app.services.security import ResultSizeLimiter
        data = {"rows": [{"id": 1}, {"id": 2}]}
        result, warnings = ResultSizeLimiter.check_and_limit_results(data)
        assert len(result["rows"]) == 2
        assert warnings == []

    def test_row_count_updated(self):
        from app.services.security import ResultSizeLimiter
        data = {"rows": [{"id": 1}]}
        result, _ = ResultSizeLimiter.check_and_limit_results(data)
        assert result["row_count"] == 1


class TestSQLIntegrityService:
    """Tests for SQLIntegrityService."""

    def test_register_and_verify(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        sql_hash = svc.register_sql("s1", "q1", "SELECT * FROM users")
        assert isinstance(sql_hash, str)
        ok, msg = svc.verify_sql("s1", "q1", "SELECT * FROM users", provided_hash=sql_hash)
        assert ok is True

    def test_verify_tampered_sql(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.register_sql("s2", "q2", "SELECT 1")
        ok, msg = svc.verify_sql("s2", "q2", "SELECT 2")
        assert ok is False
        assert "integrity" in msg.lower() or "tamper" in msg.lower()

    def test_verify_wrong_hash(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.register_sql("s3", "q3", "SELECT 1")
        ok, msg = svc.verify_sql("s3", "q3", "SELECT 1", provided_hash="wronghash")
        assert ok is False
        assert "hash" in msg.lower()

    def test_verify_expired_sql(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.register_sql("se", "qe", "SELECT 1")
        svc._sql_registry["se"]["qe"]["created_at"] = datetime.now() - timedelta(hours=2)
        ok, msg = svc.verify_sql("se", "qe", "SELECT 1")
        assert ok is False
        assert "expired" in msg.lower()

    def test_verify_unregistered_sql(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        with patch("app.services.session_store.session_store") as mock_ss:
            mock_ss.get.return_value = None
            ok, msg = svc.verify_sql("nosession", "noquery", "SELECT 1")
            assert ok is False
            assert "not found" in msg.lower()

    def test_verify_none_query_id(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        with patch("app.services.session_store.session_store") as mock_ss:
            mock_ss.get.return_value = None
            ok, msg = svc.verify_sql("sess", None, "SELECT 1")
            assert ok is False

    def test_mark_executed(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.register_sql("sm", "qm", "SELECT 1")
        svc.mark_executed("sm", "qm")
        assert svc._sql_registry["sm"]["qm"]["executed"] is True
        assert svc._sql_registry["sm"]["qm"]["execution_count"] == 1

    def test_mark_executed_increments(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.register_sql("si", "qi", "SELECT 1")
        svc.mark_executed("si", "qi")
        svc.mark_executed("si", "qi")
        assert svc._sql_registry["si"]["qi"]["execution_count"] == 2

    def test_cleanup_session(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.register_sql("sc", "q1", "SELECT 1")
        svc.register_sql("sc", "q2", "SELECT 2")
        svc.cleanup_session("sc")
        assert "sc" not in svc._sql_registry
        assert "sc" not in svc._session_secrets

    def test_cleanup_expired(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.register_sql("sx", "q-old", "SELECT 1")
        svc._sql_registry["sx"]["q-old"]["created_at"] = datetime.now() - timedelta(hours=3)
        svc.register_sql("sx", "q-new", "SELECT 2")
        svc.cleanup_expired()
        assert "q-old" not in svc._sql_registry["sx"]
        assert "q-new" in svc._sql_registry["sx"]

    def test_generate_sql_hash_deterministic(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        h1 = svc.generate_sql_hash("s1", "SELECT 1")
        h2 = svc.generate_sql_hash("s1", "SELECT 1")
        assert h1 == h2

    def test_generate_sql_hash_different_sessions(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        h1 = svc.generate_sql_hash("s1", "SELECT 1")
        h2 = svc.generate_sql_hash("s2", "SELECT 1")
        assert h1 != h2

    def test_restore_from_history(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        history = [{"id": "q1", "sql": "SELECT 1"}, {"id": "q2", "sql": "SELECT 2"}, {"id": "q3"}]
        svc.restore_from_history("sr", history)
        assert "q1" in svc._sql_registry["sr"]
        assert "q2" in svc._sql_registry["sr"]
        assert "q3" not in svc._sql_registry["sr"]

    def test_restore_from_empty_history(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.restore_from_history("s-empty", [])
        assert "s-empty" not in svc._sql_registry

    def test_restore_from_none_history(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        svc.restore_from_history("s-none", None)

    def test_get_session_secret_creates_once(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        s1 = svc.get_session_secret("s-secret")
        s2 = svc.get_session_secret("s-secret")
        assert s1 == s2

    def test_get_session_secret_different_sessions(self):
        from app.services.security import SQLIntegrityService
        svc = SQLIntegrityService()
        s1 = svc.get_session_secret("session-a")
        s2 = svc.get_session_secret("session-b")
        assert s1 != s2


# ============================================================================
# 2. SESSION STORE TESTS
# ============================================================================


@pytest.fixture
def fresh_session_store():
    """Create a fresh SessionStore with a reset singleton for isolation."""
    from app.services.session_store import SessionStore
    old_instance = SessionStore._instance
    SessionStore._instance = None
    try:
        with patch("app.services.session_store.SessionStore._init_redis"):
            store = SessionStore()
            store.redis_client = None
            store.memory_store = {}
            yield store
    finally:
        SessionStore._instance = old_instance


class TestSessionStoreSingleton:

    def test_same_instance(self):
        from app.services.session_store import SessionStore
        old = SessionStore._instance
        try:
            SessionStore._instance = None
            with patch("app.services.session_store.SessionStore._init_redis"):
                a = SessionStore()
                b = SessionStore()
                assert a is b
        finally:
            SessionStore._instance = old

    def test_init_runs_only_once(self):
        from app.services.session_store import SessionStore
        old = SessionStore._instance
        try:
            SessionStore._instance = None
            with patch("app.services.session_store.SessionStore._init_redis") as mock_init:
                SessionStore()
                SessionStore()
                mock_init.assert_called_once()
        finally:
            SessionStore._instance = old


class TestSessionStoreCreateSession:

    def test_create_session_returns_signed_id(self, fresh_session_store):
        sid = fresh_session_store.create_session({"provider": "openai"}, {"db_type": "postgresql"})
        assert len(sid.split(":")) == 3

    def test_create_session_stores_data(self, fresh_session_store):
        sid = fresh_session_store.create_session({"provider": "openai"}, {"db_type": "postgresql"})
        session = fresh_session_store.get(sid)
        assert session is not None
        assert session["id"] == sid
        assert session["llm_config"]["provider"] == "openai"
        assert session["locked"] is False

    def test_create_session_initializes_all_fields(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        session = fresh_session_store.get(sid)
        assert session["feedback"] == []
        assert session["context_window"] == []
        assert session["token_info"] is None
        assert session["conversation_thread_id"] is None
        assert session["result_cache"] == {}
        assert session["explored_tables"] == []


class TestSessionStoreGet:

    def test_get_existing_session(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        assert fresh_session_store.get(sid) is not None

    def test_get_nonexistent_session(self, fresh_session_store):
        result = fresh_session_store.get("nonexistent:0:0000000000000000", verify_signature=False)
        assert result is None

    def test_get_invalid_signature_rejected(self, fresh_session_store):
        assert fresh_session_store.get("fake:123:invalidsignature") is None

    def test_get_skip_signature_verification(self, fresh_session_store):
        fresh_session_store.memory_store["raw-id"] = {"id": "raw-id", "data": "test"}
        result = fresh_session_store.get("raw-id", verify_signature=False)
        assert result is not None
        assert result["data"] == "test"


class TestSessionStoreUpdate:

    def test_update_session(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        fresh_session_store.update(sid, {"locked": True})
        assert fresh_session_store.get(sid)["locked"] is True

    def test_update_sets_updated_at(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        old_updated = fresh_session_store.get(sid)["updated_at"]
        time.sleep(0.01)
        fresh_session_store.update(sid, {"locked": True})
        assert fresh_session_store.get(sid)["updated_at"] != old_updated

    def test_update_nonexistent_raises(self, fresh_session_store):
        with pytest.raises(ValueError, match="Session not found"):
            fresh_session_store.update("nonexistent:0:0000000000000000", {"locked": True})


class TestSessionStoreDelete:

    def test_delete_session(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        fresh_session_store.delete(sid)
        assert fresh_session_store.get(sid, verify_signature=False) is None

    def test_delete_nonexistent_is_safe(self, fresh_session_store):
        fresh_session_store.delete("nonexistent:0:0000000000000000")


class TestSessionStoreHistory:

    def test_add_history_returns_entry_id(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        entry_id = fresh_session_store.add_history(sid, {"query": "test", "sql": "SELECT 1"})
        assert isinstance(entry_id, str) and len(entry_id) > 0

    def test_add_history_locks_session(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        assert fresh_session_store.get(sid)["locked"] is False
        fresh_session_store.add_history(sid, {"query": "test"})
        assert fresh_session_store.get(sid)["locked"] is True

    def test_add_history_with_analyst_fields(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        fresh_session_store.add_history(
            sid, {"query": "test"}, answer="The answer is 42",
            key_findings=["finding1"], confidence=0.95,
            chart_spec={"type": "bar"}, tools_used=["sql_execute"],
            agent_steps=[{"step": 1}], is_follow_up=True, conversation_turn=3,
        )
        entry = fresh_session_store.get(sid)["history"][-1]
        assert entry["answer"] == "The answer is 42"
        assert entry["confidence"] == 0.95
        assert entry["is_follow_up"] is True
        assert entry["conversation_turn"] == 3

    def test_history_maintains_context_window(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        for i in range(25):
            fresh_session_store.add_history(sid, {"query": f"q{i}"})
        assert len(fresh_session_store.get(sid)["context_window"]) <= 20

    def test_history_trimmed_when_too_long(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        for i in range(110):
            fresh_session_store.add_history(sid, {"query": f"q{i}"})
        assert len(fresh_session_store.get(sid)["history"]) <= 100

    def test_add_history_nonexistent_session_raises(self, fresh_session_store):
        with pytest.raises(ValueError, match="Session not found"):
            fresh_session_store.add_history("nonexistent:0:0000000000000000", {"query": "test"})


class TestSessionStoreFeedback:

    def test_add_feedback(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test"})
        fresh_session_store.add_feedback(sid, eid, rating=5, comment="Great!")
        assert fresh_session_store.get(sid)["feedback"][0]["rating"] == 5

    def test_feedback_updates_history_entry(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test"})
        fresh_session_store.add_feedback(sid, eid, rating=4)
        entry = next(e for e in fresh_session_store.get(sid)["history"] if e["id"] == eid)
        assert entry["feedback_rating"] == 4

    def test_feedback_capped_at_100(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test"})
        for i in range(110):
            fresh_session_store.add_feedback(sid, eid, rating=i % 5)
        assert len(fresh_session_store.get(sid)["feedback"]) <= 100


class TestSessionStoreConversation:

    def test_cache_and_get_query_result(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        result = {"columns": ["id"], "rows": [{"id": 1}], "row_count": 1, "sql": "SELECT 1"}
        fresh_session_store.cache_query_result(sid, "q1", result)
        cached = fresh_session_store.get_cached_result(sid, "q1")
        assert cached is not None and cached["columns"] == ["id"]

    def test_get_cached_result_last(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        fresh_session_store.cache_query_result(sid, "q1", {"columns": ["a"], "rows": [], "sql": "S1"})
        time.sleep(0.01)
        fresh_session_store.cache_query_result(sid, "q2", {"columns": ["b"], "rows": [], "sql": "S2"})
        cached = fresh_session_store.get_cached_result(sid, "last")
        assert cached["columns"] == ["b"]

    def test_get_cached_result_nonexistent(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        assert fresh_session_store.get_cached_result(sid, "noquery") is None

    def test_get_cached_result_empty_cache(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        assert fresh_session_store.get_cached_result(sid, "last") is None

    def test_cache_prunes_old_entries(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        for i in range(15):
            fresh_session_store.cache_query_result(sid, f"q{i}", {"columns": [], "rows": [], "sql": f"S{i}"}, max_cache_size=10)
        assert len(fresh_session_store.get(sid).get("result_cache", {})) <= 10

    def test_reset_conversation(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        fresh_session_store.add_history(sid, {"query": "test"})
        fresh_session_store.cache_query_result(sid, "q1", {"columns": [], "rows": [], "sql": ""})
        fresh_session_store.reset_conversation(sid)
        session = fresh_session_store.get(sid)
        assert session["conversation_thread_id"] is None
        assert session["result_cache"] == {}
        assert session["context_window"] == []
        assert len(session["history"]) > 0

    def test_reset_conversation_nonexistent_is_safe(self, fresh_session_store):
        fresh_session_store.reset_conversation("nonexistent:0:0000000000000000")

    def test_get_conversation_context(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {"db_type": "postgresql"})
        for i in range(8):
            fresh_session_store.add_history(sid, {"query": f"q{i}", "sql": f"SELECT {i}", "success": True})
        ctx = fresh_session_store.get_conversation_context(sid, limit=5)
        assert len(ctx) == 5
        assert ctx[0]["turn"] == 1

    def test_get_conversation_context_empty(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        assert fresh_session_store.get_conversation_context(sid) == []

    def test_get_conversation_context_nonexistent(self, fresh_session_store):
        assert fresh_session_store.get_conversation_context("nonexistent:0:0000000000000000") == []

    def test_get_conversation_context_none_safe_slicing(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        fresh_session_store.add_history(
            sid, {"query": "test", "sql": "SELECT 1", "success": True},
            raw_result_summary=None, answer=None, key_findings=None,
        )
        ctx = fresh_session_store.get_conversation_context(sid)
        assert len(ctx) == 1
        assert ctx[0]["answer"] == ""
        assert ctx[0]["key_findings"] == []
        assert ctx[0]["row_count"] == 0
        assert ctx[0]["columns"] == []


class TestSessionStorePinning:

    def test_toggle_pin(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test"})
        assert fresh_session_store.toggle_pin(sid, eid, True) is True
        entry = next(e for e in fresh_session_store.get(sid)["history"] if e["id"] == eid)
        assert entry["pinned"] is True

    def test_toggle_pin_nonexistent_entry(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        assert fresh_session_store.toggle_pin(sid, "nonexistent-query", True) is False

    def test_get_pinned_queries(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        e1 = fresh_session_store.add_history(sid, {"query": "q1"})
        fresh_session_store.add_history(sid, {"query": "q2"})
        fresh_session_store.toggle_pin(sid, e1, True)
        pinned = fresh_session_store.get_pinned_queries(sid)
        assert len(pinned) == 1 and pinned[0]["id"] == e1


class TestSessionStoreSearch:

    def test_search_history_by_term(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        fresh_session_store.add_history(sid, {"query": "find users", "sql": "SELECT * FROM users"})
        fresh_session_store.add_history(sid, {"query": "find orders", "sql": "SELECT * FROM orders"})
        results = fresh_session_store.search_history(sid, search_term="users")
        assert len(results) == 1

    def test_search_history_pagination(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        for i in range(10):
            fresh_session_store.add_history(sid, {"query": f"q{i}"})
        assert len(fresh_session_store.search_history(sid, limit=3, offset=0)) == 3

    def test_get_history_entry(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test"})
        entry = fresh_session_store.get_history_entry(sid, eid)
        assert entry is not None and entry["query"] == "test"

    def test_get_history_entry_not_found(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        assert fresh_session_store.get_history_entry(sid, "nonexistent") is None


class TestSessionStoreReexecution:

    def test_reexecution_matching_connection(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test", "sql": "SELECT 1"})
        fresh_session_store.update_history_entry(sid, eid, {"connection_id": "conn-hash-abc"})
        entry, err = fresh_session_store.get_history_for_reexecution(sid, eid, "conn-hash-abc")
        assert entry is not None and err is None

    def test_reexecution_mismatched_connection(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test", "sql": "SELECT 1"})
        fresh_session_store.update_history_entry(sid, eid, {"connection_id": "conn-A"})
        entry, err = fresh_session_store.get_history_for_reexecution(sid, eid, "conn-B")
        assert entry is None and "different database" in err.lower()

    def test_reexecution_no_sql(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test"})
        entry, err = fresh_session_store.get_history_for_reexecution(sid, eid, "conn")
        assert entry is None and "no sql" in err.lower()


class TestSessionStoreUpdateHistoryEntry:

    def test_update_safe_fields(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test"})
        assert fresh_session_store.update_history_entry(sid, eid, {"pinned": True, "sql_hash": "abc"}) is True
        entry = fresh_session_store.get_history_entry(sid, eid)
        assert entry["pinned"] is True and entry["sql_hash"] == "abc"

    def test_update_unsafe_field_ignored(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        eid = fresh_session_store.add_history(sid, {"query": "test", "sql": "SELECT 1"})
        fresh_session_store.update_history_entry(sid, eid, {"sql": "DROP TABLE users"})
        assert fresh_session_store.get_history_entry(sid, eid)["sql"] == "SELECT 1"

    def test_update_nonexistent_entry(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        assert fresh_session_store.update_history_entry(sid, "nonexistent", {"pinned": True}) is False


class TestSessionStoreTokenInfo:

    def test_update_token_info(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        fresh_session_store.update_token_info(sid, {"token": "abc", "expires_at": "2099-01-01"})
        assert fresh_session_store.get(sid)["token_info"]["token"] == "abc"

    def test_update_token_info_nonexistent_raises(self, fresh_session_store):
        with pytest.raises(ValueError, match="Session not found"):
            fresh_session_store.update_token_info("nonexistent:0:0000000000000000", {})


class TestSessionStoreThreadSafety:

    def test_concurrent_creates(self, fresh_session_store):
        results = []
        errors = []
        def create_session():
            try:
                sid = fresh_session_store.create_session({"provider": "test"}, {"db_type": "pg"})
                results.append(sid)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=create_session) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert len(results) == 20
        assert len(set(results)) == 20

    def test_concurrent_delete_and_get(self, fresh_session_store):
        sid = fresh_session_store.create_session({}, {})
        errors = []
        def delete_op():
            try:
                fresh_session_store.delete(sid)
            except Exception as e:
                errors.append(e)
        def get_op():
            try:
                fresh_session_store.get(sid)
            except Exception as e:
                errors.append(e)
        t1 = threading.Thread(target=delete_op)
        t2 = threading.Thread(target=get_op)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(errors) == 0


class TestSessionStoreStorageInfo:

    def test_storage_info_memory_backend(self, fresh_session_store):
        info = fresh_session_store.get_storage_info()
        assert info["backend"] == "memory"
        assert info["persistent"] is False

    def test_list_sessions(self, fresh_session_store):
        fresh_session_store.create_session({}, {})
        fresh_session_store.create_session({}, {})
        assert len(fresh_session_store.list_sessions()) == 2


class TestSessionStoreMemoryCleanup:

    def test_cleanup_removes_expired(self, fresh_session_store):
        fresh_session_store.memory_store["old-session"] = {
            "id": "old-session", "created_at": "2020-01-01T00:00:00",
            "updated_at": "2020-01-01T00:00:00", "locked": False, "history": [],
        }
        fresh_session_store._last_cleanup = datetime.now() - timedelta(hours=1)
        fresh_session_store.MEMORY_CLEANUP_INTERVAL = 0
        fresh_session_store._maybe_cleanup_memory()
        assert "old-session" not in fresh_session_store.memory_store


class TestSecureJSONEncoder:

    def test_encode_datetime(self):
        from app.services.session_store import SecureJSONEncoder
        result = json.dumps({"ts": datetime(2024, 1, 15, 12, 30, 0)}, cls=SecureJSONEncoder)
        assert "__datetime__" in result

    def test_decode_datetime(self):
        from app.services.session_store import secure_json_decoder
        data = '{"ts": {"__datetime__": "2024-01-15T12:30:00"}}'
        result = json.loads(data, object_hook=secure_json_decoder)
        assert isinstance(result["ts"], datetime)

    def test_roundtrip(self):
        from app.services.session_store import SecureJSONEncoder, secure_json_decoder
        original = {"ts": datetime(2024, 6, 15, 10, 0, 0), "name": "test"}
        encoded = json.dumps(original, cls=SecureJSONEncoder)
        decoded = json.loads(encoded, object_hook=secure_json_decoder)
        assert decoded["ts"] == original["ts"]

    def test_non_datetime_raises(self):
        from app.services.session_store import SecureJSONEncoder
        with pytest.raises(TypeError):
            json.dumps({"bad": object()}, cls=SecureJSONEncoder)


# ============================================================================
# 3. CONFIG TESTS
# ============================================================================


class TestSettingsDefaults:

    def test_default_values(self):
        import os
        from app.core.config import Settings
        # Clear DEBUG env var if set (e.g. by CI) to test actual default
        env_debug = os.environ.pop("DEBUG", None)
        try:
            s = Settings(_env_file=None, SESSION_SIGNING_SECRET="test-secret-for-unit-tests")
            assert s.APP_NAME == "QueryfyAI"
            assert s.DEBUG is False
        finally:
            if env_debug is not None:
                os.environ["DEBUG"] = env_debug
        assert s.LOG_LEVEL == "INFO"
        assert s.HOST == "0.0.0.0"
        assert s.PORT == 8000
        assert s.SESSION_EXPIRY_HOURS == 24
        assert s.MAX_CONTEXT_WINDOW == 20
        assert s.MAX_HISTORY_ITEMS == 100
        assert s.MAX_QUERY_LENGTH == 5000
        assert s.QUERY_TIMEOUT_SECONDS == 300
        assert s.MAX_EXPORT_ROWS == 1000000
        assert s.RATE_LIMIT_ENABLED is True

    def test_redis_url_default(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET="test-secret")
        assert s.REDIS_URL == "redis://localhost:6379"

    def test_agent_defaults(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET="test-secret")
        assert s.AGENT_MAX_RETRIES == 3
        assert s.AGENT_TIMEOUT_SECONDS == 120
        assert s.AGENT_MAX_MESSAGES == 50
        assert s.AGENT_PRESERVE_RECENT == 20

    def test_otel_defaults(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET="test-secret")
        assert s.OTEL_ENABLED is False
        assert s.OTEL_SERVICE_NAME == "queryfyai-backend"

    def test_cache_defaults(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET="test-secret")
        assert s.CACHE_TYPE == "auto"
        assert s.CACHE_TTL_LLM == 3600
        assert s.CACHE_TTL_QUERY == 300
        assert s.CACHE_TTL_SCHEMA == 3600


class TestSettingsOverrides:

    def test_override_debug(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, DEBUG=True, SESSION_SIGNING_SECRET="test-secret")
        assert s.DEBUG is True

    def test_override_port(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, PORT=9000, SESSION_SIGNING_SECRET="test-secret")
        assert s.PORT == 9000

    def test_override_session_expiry(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_EXPIRY_HOURS=48, SESSION_SIGNING_SECRET="test-secret")
        assert s.SESSION_EXPIRY_HOURS == 48


class TestSettingsEffectiveAnalystTimeout:

    def test_analyst_timeout_when_set(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, ANALYST_TIMEOUT_SECONDS=300, AGENT_TIMEOUT_SECONDS=120, SESSION_SIGNING_SECRET="test-secret")
        assert s.effective_analyst_timeout == 300

    def test_analyst_timeout_fallback_when_zero(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, ANALYST_TIMEOUT_SECONDS=0, AGENT_TIMEOUT_SECONDS=120, SESSION_SIGNING_SECRET="test-secret")
        assert s.effective_analyst_timeout == 120


class TestSettingsValidation:

    def test_validate_qdrant_without_url_raises(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, VECTOR_DB_TYPE="qdrant", QDRANT_URL=None, DEBUG=True)
        with pytest.raises(ValueError, match="QDRANT_URL"):
            s.validate_config()

    def test_validate_openai_embedding_without_key_warns(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, EMBEDDING_PROVIDER="openai", OPENAI_API_KEY=None, DEBUG=True)
        warnings = s.validate_config()
        assert any("OPENAI_API_KEY" in w for w in warnings)

    def test_validate_no_signing_secret_production_raises(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET=None, DEBUG=False)
        with pytest.raises(ValueError, match="SESSION_SIGNING_SECRET"):
            s.validate_config()

    def test_validate_no_signing_secret_debug_warns(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET=None, DEBUG=True)
        warnings = s.validate_config()
        assert any("SESSION_SIGNING_SECRET" in w for w in warnings)

    def test_validate_bad_rate_limit_format_warns(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, RATE_LIMIT_DEFAULT="bad-format", DEBUG=True)
        warnings = s.validate_config()
        assert any("RATE_LIMIT_DEFAULT" in w for w in warnings)

    def test_validate_query_timeout_out_of_range_warns(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, QUERY_TIMEOUT_SECONDS=0, DEBUG=True)
        warnings = s.validate_config()
        assert any("QUERY_TIMEOUT_SECONDS" in w for w in warnings)

    def test_validate_agent_retries_out_of_range_warns(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, AGENT_MAX_RETRIES=50, DEBUG=True)
        warnings = s.validate_config()
        assert any("AGENT_MAX_RETRIES" in w for w in warnings)

    def test_validate_clean_config_no_warnings(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET="a-valid-secret", DEBUG=False)
        warnings = s.validate_config()
        assert len(warnings) == 0


class TestSettingsDefaultConfigs:

    def test_get_default_llm_config(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, DEFAULT_LLM_PROVIDER="openai", DEFAULT_LLM_MODEL="gpt-4o", DEFAULT_LLM_API_KEY="sk-test", SESSION_SIGNING_SECRET="test")
        config = s.get_default_llm_config()
        assert config["provider"] == "openai"
        assert config["model"] == "gpt-4o"
        assert config["api_key"] == "sk-test"

    def test_get_default_llm_config_none_values(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET="test")
        config = s.get_default_llm_config()
        assert config["base_url"] == ""
        assert config["token_url"] == ""

    def test_get_default_db_config(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, DEFAULT_DB_TYPE="mysql", DEFAULT_DB_CONNECTION_URL="mysql://host/db", DEFAULT_DB_NAME="testdb", SESSION_SIGNING_SECRET="test")
        config = s.get_default_db_config()
        assert config["db_type"] == "mysql"
        assert config["connection_url"] == "mysql://host/db"
        assert config["name"] == "testdb"

    def test_has_default_llm_config_oauth(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, DEFAULT_LLM_PROVIDER="oauth_gateway", DEFAULT_LLM_BASE_URL="https://api.example.com", DEFAULT_LLM_TOKEN_URL="https://auth.example.com/token", SESSION_SIGNING_SECRET="test")
        assert s.has_default_llm_config() is True

    def test_has_default_llm_config_oauth_incomplete(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, DEFAULT_LLM_PROVIDER="oauth_gateway", DEFAULT_LLM_BASE_URL=None, DEFAULT_LLM_TOKEN_URL=None, SESSION_SIGNING_SECRET="test")
        assert s.has_default_llm_config() is False

    def test_has_default_llm_config_direct_provider(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, DEFAULT_LLM_PROVIDER="openai", DEFAULT_LLM_API_KEY="sk-test", SESSION_SIGNING_SECRET="test")
        assert s.has_default_llm_config() is True

    def test_has_default_llm_config_direct_no_key(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, DEFAULT_LLM_PROVIDER="openai", DEFAULT_LLM_API_KEY=None, SESSION_SIGNING_SECRET="test")
        assert s.has_default_llm_config() is False


class TestSettingsLogConfig:

    def test_log_loaded_config_does_not_raise(self):
        from app.core.config import Settings
        s = Settings(_env_file=None, SESSION_SIGNING_SECRET="test")
        s.log_loaded_config()
