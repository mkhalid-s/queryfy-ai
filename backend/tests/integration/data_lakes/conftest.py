"""
Data-lake integration test fixtures.

Tests under ``tests/integration/data_lakes`` exercise real / emulated
drivers. Availability fixtures decide at collection time whether each
backend is reachable; tests are skipped cleanly if not.

How to run the full suite:
  docker compose -f docker-compose.integration.yml up -d
  cd backend && pytest -m data_lake_integration
  docker compose -f docker-compose.integration.yml down -v

Environment-variable overrides:
  BIGQUERY_EMULATOR_URL   default http://localhost:9050
  TRINO_URL               default http://localhost:8089
  MINIO_URL               default http://localhost:9000
  GOOGLE_APPLICATION_CREDENTIALS  presence → enables real-BQ tests
  BIGQUERY_PROJECT        required with creds for real-BQ tests
  SNOWFLAKE_ACCOUNT / _USER / _PASSWORD  real-Snowflake tests
"""

from __future__ import annotations

import os
import socket
from typing import Optional
from urllib.parse import urlparse

import pytest


# --------------------------------------------------------------------------
# URL defaults (match docker-compose.integration.yml)
# --------------------------------------------------------------------------

BIGQUERY_EMULATOR_URL = os.environ.get(
    "BIGQUERY_EMULATOR_URL", "http://localhost:9050"
)
TRINO_URL = os.environ.get("TRINO_URL", "http://localhost:8089")
MINIO_URL = os.environ.get("MINIO_URL", "http://localhost:9000")


# --------------------------------------------------------------------------
# Reachability probes — fast socket connect, no extra deps required
# --------------------------------------------------------------------------


def _probe_tcp(url: str, timeout: float = 0.5) -> bool:
    """Return True if a TCP connection to the URL's host:port succeeds."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def bigquery_emulator_url() -> str:
    if not _probe_tcp(BIGQUERY_EMULATOR_URL):
        pytest.skip(
            f"BigQuery emulator not reachable at {BIGQUERY_EMULATOR_URL}. "
            f"Run: docker compose -f docker-compose.integration.yml up -d"
        )
    return BIGQUERY_EMULATOR_URL


@pytest.fixture(scope="session")
def trino_url() -> str:
    if not _probe_tcp(TRINO_URL):
        pytest.skip(
            f"Trino not reachable at {TRINO_URL}. "
            f"Run: docker compose -f docker-compose.integration.yml up -d"
        )
    return TRINO_URL


@pytest.fixture(scope="session")
def minio_url() -> str:
    if not _probe_tcp(MINIO_URL):
        pytest.skip(
            f"MinIO not reachable at {MINIO_URL}. "
            f"Run: docker compose -f docker-compose.integration.yml up -d"
        )
    return MINIO_URL


# --------------------------------------------------------------------------
# Real-credential gates (separate from emulator tests)
# --------------------------------------------------------------------------


def _has_real_bigquery_creds() -> bool:
    return bool(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        and os.environ.get("BIGQUERY_PROJECT")
    )


def _has_real_snowflake_creds() -> bool:
    return bool(
        os.environ.get("SNOWFLAKE_ACCOUNT")
        and os.environ.get("SNOWFLAKE_USER")
        and os.environ.get("SNOWFLAKE_PASSWORD")
    )


@pytest.fixture(scope="session")
def real_bigquery_project() -> Optional[str]:
    if not _has_real_bigquery_creds():
        pytest.skip(
            "Real BigQuery not configured. Set GOOGLE_APPLICATION_CREDENTIALS "
            "and BIGQUERY_PROJECT to enable."
        )
    return os.environ["BIGQUERY_PROJECT"]


@pytest.fixture(scope="session")
def real_snowflake_account() -> Optional[str]:
    if not _has_real_snowflake_creds():
        pytest.skip(
            "Real Snowflake not configured. Set SNOWFLAKE_ACCOUNT, "
            "SNOWFLAKE_USER, SNOWFLAKE_PASSWORD."
        )
    return os.environ["SNOWFLAKE_ACCOUNT"]


# --------------------------------------------------------------------------
# Pytest hook: skip emulator tests if the marker's fixture is unreachable.
# Also auto-apply ``data_lake_integration`` marker to every test in this
# directory so ``pytest -m data_lake_integration`` is the right entry.
# --------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    for item in items:
        # Auto-mark any test whose file lives under data_lakes/ as
        # data_lake_integration so the marker selection works even if a
        # test author forgets to tag the test explicitly.
        if "/integration/data_lakes/" in str(item.fspath):
            item.add_marker(pytest.mark.data_lake_integration)
