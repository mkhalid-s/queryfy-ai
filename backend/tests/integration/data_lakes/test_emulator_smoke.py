"""
Smoke tests for the integration emulator stack.

Verifies the ``docker-compose.integration.yml`` services are responsive
and speaking the protocols we expect. Skipped cleanly when the stack
isn't running.

These are NOT driver integration tests — those land with Phase 3b.3
(BigQuery) and 3b.4 (Snowflake). This file only proves the infra is
wired correctly so driver tests have something to aim at.
"""

from __future__ import annotations

import pytest


@pytest.mark.requires_bigquery_emulator
def test_bigquery_emulator_responds(bigquery_emulator_url) -> None:
    """The BigQuery emulator should serve its discovery doc."""
    import urllib.request

    with urllib.request.urlopen(
        f"{bigquery_emulator_url}/discovery/v1/apis/bigquery/v2/rest",
        timeout=5,
    ) as resp:
        assert resp.status == 200


@pytest.mark.requires_trino
def test_trino_info_endpoint(trino_url) -> None:
    """Trino's /v1/info should return server state."""
    import json
    import urllib.request

    with urllib.request.urlopen(f"{trino_url}/v1/info", timeout=5) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode())
        # Trino returns a mix of flags; presence of any of these keys is
        # enough to confirm we're talking to Trino, not some other thing
        # squatting on the port.
        assert any(k in body for k in ("nodeVersion", "environment", "uptime"))


def test_minio_reachable(minio_url) -> None:
    """MinIO's / endpoint returns a 403 by default (no anonymous access)
    but responding at all proves the service is up."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(minio_url, timeout=5) as resp:
            # 200 would be surprising; we primarily care that MinIO
            # replies with a valid HTTP status, not a connection error.
            assert resp.status in (200, 403, 400)
    except urllib.error.HTTPError as e:
        # MinIO returns 403 for anonymous root requests — still proves
        # the service is listening and speaks HTTP.
        assert e.code in (403, 400)
