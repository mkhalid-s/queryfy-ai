#!/usr/bin/env python3
"""
Phase 1 Demo Pre-flight Configuration Validator.

Checks the QueryfyAI backend configuration for conditions that have historically
caused demo-time failures (see docs/architecture-audit-2026-04-16.md). Each
check reports at one of three severities:

    ERROR   — demo will fail if not addressed (exits non-zero)
    WARNING — demo can proceed but with caveats (logged, exit 0)
    INFO    — status output (no failure)

Run
---
    $ cd backend && python scripts/validate_demo_config.py
    $ cd backend && python scripts/validate_demo_config.py --strict
        # --strict: treat warnings as errors (CI-friendly)

Exit codes
----------
    0 — ready to demo (warnings are acceptable unless --strict is given)
    1 — blocked by at least one ERROR-severity check (or warning in --strict)

The script is intentionally dependency-light: it only touches public settings
attributes and makes best-effort connectivity probes so it can run in a
CI container that doesn't have every backend extra installed.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

# Make ``app`` importable when this script is run from backend/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


# -----------------------------------------------------------------------------
# Result types
# -----------------------------------------------------------------------------


ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"


@dataclass
class CheckResult:
    severity: str
    name: str
    message: str
    hint: Optional[str] = None


@dataclass
class Report:
    results: List[CheckResult] = field(default_factory=list)

    def add(
        self,
        severity: str,
        name: str,
        message: str,
        hint: Optional[str] = None,
    ) -> None:
        self.results.append(CheckResult(severity, name, message, hint))

    def has_errors(self) -> bool:
        return any(r.severity == ERROR for r in self.results)

    def has_warnings(self) -> bool:
        return any(r.severity == WARNING for r in self.results)

    def summary(self) -> str:
        errs = sum(1 for r in self.results if r.severity == ERROR)
        warns = sum(1 for r in self.results if r.severity == WARNING)
        infos = sum(1 for r in self.results if r.severity == INFO)
        return f"{errs} error(s), {warns} warning(s), {infos} info"


# -----------------------------------------------------------------------------
# Individual checks
# -----------------------------------------------------------------------------


def _load_settings() -> Optional[object]:
    """
    Import ``app.core.config.settings`` lazily so a malformed .env file shows
    up as an ERROR rather than an uncatchable ImportError at module load.
    """
    try:
        from app.core.config import settings  # type: ignore[import-not-found]
    except Exception as e:  # pragma: no cover - defensive
        return e  # type: ignore[return-value]
    return settings


def check_settings_import(report: Report) -> Optional[object]:
    """Verify the Settings object loads cleanly from .env."""
    settings = _load_settings()
    if isinstance(settings, Exception):
        report.add(
            ERROR,
            "settings.import",
            f"Failed to import app.core.config.settings: {settings}",
            "Check .env syntax and required env vars. See backend/.env.example.",
        )
        return None
    report.add(INFO, "settings.import", "Settings loaded successfully")
    return settings


def check_fix_flags(report: Report, settings: object) -> None:
    """
    Report Phase 1 fix-flag state and check for dependency misconfigurations.

    Catches the HIGH-severity "silent rollback" discovered in cross-cutting
    validation: if ``FIX_INSIGHT_DEDUPLICATION`` is on but
    ``FIX_COLUMN_NAME_FIELD`` is off, dedup becomes a no-op because all
    insights carry ``column_name=""`` and every pair is unique. The app
    still starts but produces the exact duplicate-insight bug the fix was
    supposed to eliminate.
    """
    flags = [
        "FIX_JSON_ERROR_DETECTION",
        "FIX_SUCCESS_FIELD_CHECK",
        "FIX_COLUMN_NAME_FIELD",
        "FIX_INSIGHT_DEDUPLICATION",
        "FIX_SMART_ID_EXCLUSION",
        "FIX_DATE_BASED_TRENDS",
        "FIX_DATA_LAKE_TIMEOUT",
    ]
    disabled = [f for f in flags if hasattr(settings, f) and not getattr(settings, f)]
    if disabled:
        report.add(
            WARNING,
            "fix_flags.disabled",
            f"{len(disabled)} Phase 1 fix flag(s) disabled: {', '.join(disabled)}",
            "Phase 1 fixes are off; affected bugs may resurface. "
            "Set these to True unless you are intentionally rolling back.",
        )
    else:
        report.add(INFO, "fix_flags", "All Phase 1 reliability fixes enabled")

    # Dependency: dedup (Day 2b) needs column_name (Day 2a) to group on.
    if (
        getattr(settings, "FIX_INSIGHT_DEDUPLICATION", True)
        and not getattr(settings, "FIX_COLUMN_NAME_FIELD", True)
    ):
        report.add(
            ERROR,
            "fix_flags.dep_insight_dedup_needs_column_name",
            "FIX_INSIGHT_DEDUPLICATION=True requires FIX_COLUMN_NAME_FIELD=True",
            "Dedup groups by (type, column_name). With column_name off, all "
            "insights share an empty key and no dedup happens. Turn "
            "FIX_COLUMN_NAME_FIELD back on OR disable FIX_INSIGHT_DEDUPLICATION.",
        )


def check_vector_db(report: Report, settings: object) -> None:
    """Verify the vector DB backend specified in settings is usable."""
    vdb_type = getattr(settings, "VECTOR_DB_TYPE", "chromadb")
    if vdb_type == "qdrant":
        qdrant_url = getattr(settings, "QDRANT_URL", None)
        if not qdrant_url:
            report.add(
                ERROR,
                "vector_db.qdrant_url",
                "VECTOR_DB_TYPE=qdrant but QDRANT_URL is not set",
                "Set QDRANT_URL=http://host:6333 in .env, or switch to VECTOR_DB_TYPE=chromadb.",
            )
            return
        # Best-effort connectivity probe (TCP only — avoids adding deps).
        try:
            parsed = urlparse(qdrant_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 6333
            with socket.create_connection((host, port), timeout=3.0):
                report.add(INFO, "vector_db.qdrant", f"Qdrant reachable at {host}:{port}")
        except OSError as e:
            report.add(
                ERROR,
                "vector_db.qdrant_reachable",
                f"Qdrant {qdrant_url} not reachable: {e}",
                "Start Qdrant (docker run -p 6333:6333 qdrant/qdrant) or check QDRANT_URL.",
            )
        return

    if vdb_type == "chromadb":
        persist_dir = getattr(settings, "CHROMA_PERSIST_DIR", "./data/chroma_db")
        path = Path(persist_dir)
        if not path.exists():
            report.add(
                WARNING,
                "vector_db.chromadb_dir",
                f"CHROMA_PERSIST_DIR {persist_dir} does not exist yet",
                "First run will create it. If running from an unusual cwd, set an absolute path.",
            )
            return
        if not os.access(path, os.W_OK):
            report.add(
                ERROR,
                "vector_db.chromadb_perm",
                f"CHROMA_PERSIST_DIR {persist_dir} is not writable",
                "Fix file permissions on the persist directory.",
            )
            return
        report.add(INFO, "vector_db.chromadb", f"ChromaDB persist dir OK: {persist_dir}")
        return

    report.add(
        WARNING,
        "vector_db.unknown_type",
        f"Unknown VECTOR_DB_TYPE={vdb_type!r}",
        "Use 'chromadb' or 'qdrant'.",
    )


def check_embeddings(report: Report, settings: object) -> None:
    """Catch EMBEDDING_PROVIDER / API-key mismatches before first query."""
    provider = getattr(settings, "EMBEDDING_PROVIDER", "local")
    if provider == "openai" and not getattr(settings, "OPENAI_API_KEY", None):
        report.add(
            WARNING,
            "embeddings.openai_key",
            "EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set",
            "Set OPENAI_API_KEY in .env, or switch EMBEDDING_PROVIDER=local for a local model.",
        )
        return
    if provider == "local":
        report.add(INFO, "embeddings", "Using local embeddings (sentence-transformers)")
        return
    if provider == "none":
        report.add(
            WARNING,
            "embeddings.disabled",
            "EMBEDDING_PROVIDER=none — semantic search over schema is disabled",
            "Agent will fall back to full schema dump; adequate for small DBs only.",
        )
        return
    report.add(INFO, "embeddings.provider", f"Provider: {provider}")


def check_database_url(report: Report, settings: object) -> None:
    """DATABASE_URL is required for checkpoint persistence (analyst mode)."""
    db_url = getattr(settings, "DATABASE_URL", None)
    if not db_url:
        report.add(
            WARNING,
            "database_url",
            "DATABASE_URL not set — LangGraph checkpointer will use in-memory store",
            "Sessions will not survive restarts. Set DATABASE_URL for production / demo persistence.",
        )
        return
    try:
        parsed = urlparse(db_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=3.0):
            report.add(INFO, "database_url", f"PostgreSQL reachable at {host}:{port}")
    except OSError as e:
        report.add(
            ERROR,
            "database_url.reachable",
            f"DATABASE_URL target not reachable: {e}",
            "Start Postgres and ensure the host:port in DATABASE_URL is correct.",
        )


def check_redis(report: Report, settings: object) -> None:
    """Redis is optional but strongly recommended for multi-worker deployments."""
    redis_url = getattr(settings, "REDIS_URL", None)
    if not redis_url:
        report.add(
            WARNING,
            "redis",
            "REDIS_URL not set — session store and cache will use in-memory fallback",
            "Multi-worker deploys REQUIRE Redis. Fine for single-worker demos.",
        )
        return
    try:
        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=3.0):
            report.add(INFO, "redis", f"Redis reachable at {host}:{port}")
    except OSError as e:
        report.add(
            WARNING,
            "redis.reachable",
            f"REDIS_URL set but not reachable: {e}",
            "Backend will fall back to in-memory store; distributed locking is no longer safe.",
        )


def check_llm_config(report: Report, settings: object) -> None:
    """Verify a working LLM default is configured (either OAuth gateway or direct)."""
    has_defaults = False
    if hasattr(settings, "has_default_llm_config"):
        try:
            has_defaults = bool(settings.has_default_llm_config())
        except Exception as e:
            report.add(
                WARNING,
                "llm.defaults_check_failed",
                f"has_default_llm_config() raised: {e}",
            )
            return
    if not has_defaults:
        report.add(
            WARNING,
            "llm.no_defaults",
            "No DEFAULT_LLM_* config set — users must configure an LLM per session",
            "Set DEFAULT_LLM_PROVIDER + credentials in .env for a one-click demo.",
        )
        return
    provider = getattr(settings, "DEFAULT_LLM_PROVIDER", "unknown")
    report.add(INFO, "llm.defaults", f"Default LLM configured (provider={provider})")


def check_agent_timeout(report: Report, settings: object) -> None:
    """Warn when AGENT_TOOL_TIMEOUT is too short for data-lake queries."""
    timeout = getattr(settings, "AGENT_TOOL_TIMEOUT", 30)
    fix_enabled = getattr(settings, "FIX_DATA_LAKE_TIMEOUT", True)
    if timeout < 30:
        report.add(
            WARNING,
            "agent_tool_timeout.low",
            f"AGENT_TOOL_TIMEOUT={timeout}s is below 30s baseline",
            "Tool executions will be killed prematurely for anything non-trivial.",
        )
    if not fix_enabled:
        report.add(
            WARNING,
            "agent_tool_timeout.no_data_lake_fix",
            "FIX_DATA_LAKE_TIMEOUT=False disables the per-DB-type extension",
            "Data-lake queries (BigQuery/Snowflake/Athena) will time out at the global value.",
        )
    else:
        report.add(
            INFO,
            "agent_tool_timeout",
            f"Base={timeout}s; data-lake DBs extended to 300s (fix enabled)",
        )


def check_telemetry(report: Report, settings: object) -> None:
    """OTEL off makes post-demo fix validation harder but doesn't block."""
    if not getattr(settings, "OTEL_ENABLED", False):
        report.add(
            WARNING,
            "telemetry.otel",
            "OTEL_ENABLED=false — no tracing data for debugging",
            "Set OTEL_ENABLED=true to emit spans to OTEL_EXPORTER_OTLP_ENDPOINT.",
        )
    else:
        endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "(unset)")
        report.add(INFO, "telemetry.otel", f"Tracing enabled → {endpoint}")


def check_debug_and_signing(report: Report, settings: object) -> None:
    """Production-readiness flags."""
    debug = getattr(settings, "DEBUG", False)
    signing_secret = getattr(settings, "SESSION_SIGNING_SECRET", None)
    if debug and signing_secret:
        report.add(INFO, "session_signing", "Session signing secret present (sessions survive restart)")
    elif debug and not signing_secret:
        report.add(
            WARNING,
            "session_signing.none",
            "SESSION_SIGNING_SECRET not set — sessions lost on restart",
            "Fine for dev; generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"",
        )
    elif not debug and not signing_secret:
        # validate_config() in Settings already raises for this combo; catch it here too.
        report.add(
            ERROR,
            "session_signing.missing_in_prod",
            "SESSION_SIGNING_SECRET required when DEBUG=False",
            "Generate: python -c \"import secrets; print(secrets.token_hex(32))\" and set SESSION_SIGNING_SECRET.",
        )


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------


_SEVERITY_COLOR = {
    ERROR: "\x1b[31m",   # red
    WARNING: "\x1b[33m", # yellow
    INFO: "\x1b[32m",    # green
}
_RESET = "\x1b[0m"


def _color(severity: str) -> str:
    if not sys.stdout.isatty():
        return ""
    return _SEVERITY_COLOR.get(severity, "")


def _print_report(report: Report) -> None:
    print("\n=== QueryfyAI Phase 1 demo pre-flight ===\n")
    for r in report.results:
        prefix = f"{_color(r.severity)}{r.severity:<7}{_RESET if _color(r.severity) else ''}"
        print(f"  {prefix}  {r.name}: {r.message}")
        if r.hint:
            print(f"           → {r.hint}")
    print(f"\n  {report.summary()}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (CI-friendly). Default: warnings exit 0.",
    )
    args = parser.parse_args()

    report = Report()

    settings = check_settings_import(report)
    if settings is None:
        _print_report(report)
        return 1  # settings failed to load; nothing else to check

    check_fix_flags(report, settings)
    check_vector_db(report, settings)
    check_embeddings(report, settings)
    check_database_url(report, settings)
    check_redis(report, settings)
    check_llm_config(report, settings)
    check_agent_timeout(report, settings)
    check_telemetry(report, settings)
    check_debug_and_signing(report, settings)

    _print_report(report)

    if report.has_errors():
        return 1
    if args.strict and report.has_warnings():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
