"""
BIRD Mini-Dev Dataset Loader

Loads the 500-question BIRD Mini-Dev benchmark for text-to-SQL evaluation.
Each question targets one of ~11 SQLite databases bundled with the dataset.

Source: https://github.com/bird-bench/mini_dev
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, List
from urllib.request import urlopen

from benchmarks.core.dataset import BenchmarkDataset
from benchmarks.core.types import BenchmarkCase, DatabaseCategory, Difficulty

logger = logging.getLogger(__name__)

# Source repository (documentation)
REPO_URL = "https://github.com/bird-bench/mini_dev"

# Direct download link for BIRD Mini-Dev complete package
# Hosted on Aliyun OSS (Alibaba Cloud) - more reliable for CI/CD than Google Drive
BIRD_DOWNLOAD_URL = "https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip"

_DIFFICULTY_MAP = {
    "simple": Difficulty.SIMPLE,
    "moderate": Difficulty.MODERATE,
    "challenging": Difficulty.CHALLENGING,
    "extra": Difficulty.EXTRA_HARD,
    "extra hard": Difficulty.EXTRA_HARD,
    "extra_hard": Difficulty.EXTRA_HARD,
}


class BirdMiniDevDataset(BenchmarkDataset):
    NAME = "bird-mini-dev"
    DESCRIPTION = "500 text-to-SQL questions across ~11 SQLite databases"
    DB_TYPE = DatabaseCategory.SQL
    SOURCE_URL = REPO_URL
    TOTAL_CASES = 500

    def __init__(self) -> None:
        self._schema_cache: Dict[str, str] = {}

    def load(self, data_dir: Path) -> List[BenchmarkCase]:
        """Load BIRD Mini-Dev questions from the JSON file.

        Expected layout::

            data_dir/bird-mini-dev/mini_dev_sqlite.json
            data_dir/bird-mini-dev/dev_databases/{db_id}/{db_id}.sqlite
        """
        bird_dir = data_dir / "bird-mini-dev"
        questions_file = bird_dir / "mini_dev_sqlite.json"

        if not questions_file.exists():
            raise FileNotFoundError(
                f"BIRD data not found at {questions_file}. "
                f"Run download() first."
            )

        with open(questions_file) as f:
            raw = json.load(f)

        cases: List[BenchmarkCase] = []
        for item in raw:
            db_id = item["db_id"]
            difficulty_str = item.get("difficulty", "simple").lower()
            difficulty = _DIFFICULTY_MAP.get(difficulty_str, Difficulty.SIMPLE)

            # Extract schema lazily (only once per db_id)
            schema = self._extract_schema(bird_dir, db_id)

            cases.append(
                BenchmarkCase(
                    case_id=f"bird_{item['question_id']}",
                    natural_language=item["question"],
                    gold_query=item["SQL"],
                    db_name=db_id,
                    db_type=DatabaseCategory.SQL,
                    difficulty=difficulty,
                    evidence=item.get("evidence", ""),
                    schema_context=schema,
                )
            )

        logger.info("Loaded %d BIRD Mini-Dev cases", len(cases))
        return cases

    def download(self, data_dir: Path) -> None:
        """Download BIRD Mini-Dev complete package from Aliyun OSS.

        The data is no longer in the GitHub repository - it's distributed
        via Aliyun OSS (Alibaba Cloud).
        Source: https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip
        """
        bird_dir = data_dir / "bird-mini-dev"
        questions_file = bird_dir / "mini_dev_sqlite.json"

        if questions_file.exists():
            logger.info("BIRD Mini-Dev already present at %s", bird_dir)
            return

        bird_dir.mkdir(parents=True, exist_ok=True)

        try:
            logger.info("Downloading BIRD Mini-Dev from Aliyun OSS...")
            logger.info("URL: %s", BIRD_DOWNLOAD_URL)

            # Download to temporary file
            tmp_path = None
            try:
                # Create and write to temp file
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_file:
                    tmp_path = Path(tmp_file.name)

                    # Download from Aliyun OSS (direct download, no confirmation needed)
                    logger.info("Starting download...")
                    with urlopen(BIRD_DOWNLOAD_URL) as response:
                        # Check response headers
                        content_type = response.headers.get('content-type', 'unknown')
                        total_size = int(response.headers.get('content-length', 0))
                        logger.info(f"Content-Type: {content_type}")
                        logger.info(f"Content-Length: {total_size} bytes ({total_size / (1024*1024):.1f} MB)")

                        downloaded = 0
                        chunk_size = 8192
                        first_chunk = True

                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break

                            # Check first chunk to see if it's HTML (error page)
                            if first_chunk:
                                first_bytes = chunk[:100]
                                if first_bytes.startswith(b'<!DOCTYPE') or first_bytes.startswith(b'<html'):
                                    logger.error("Received HTML instead of ZIP file!")
                                    logger.error(f"First 100 bytes: {first_bytes}")
                                    raise ValueError("URL returned HTML page instead of ZIP file")
                                elif first_bytes.startswith(b'PK'):  # ZIP magic number
                                    logger.info("Confirmed ZIP file signature (PK)")
                                else:
                                    logger.warning(f"Unknown file signature: {first_bytes[:4]}")
                                first_chunk = False

                            tmp_file.write(chunk)
                            downloaded += len(chunk)

                            # Log progress every 10MB
                            if downloaded % (10 * 1024 * 1024) < chunk_size:
                                if total_size > 0:
                                    percent = (downloaded / total_size) * 100
                                    logger.info(f"Downloaded: {downloaded / (1024*1024):.1f} MB ({percent:.1f}%)")
                                else:
                                    logger.info(f"Downloaded: {downloaded / (1024*1024):.1f} MB")

                    logger.info(f"Download complete: {downloaded / (1024*1024):.1f} MB")

                # File is now closed, we can safely unzip it
                logger.info("Extracting...")
                import zipfile
                with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                        # Extract to a temporary directory first
                        with tempfile.TemporaryDirectory() as extract_dir:
                            zip_ref.extractall(extract_dir)
                            extract_path = Path(extract_dir)

                            # Find data directory in extracted content
                            # The minidev.zip has structure: minidev/MINIDEV/
                            mini_dev_data = None

                            # Look for common patterns
                            for pattern in ["minidev/MINIDEV", "MINIDEV", "mini_dev_data"]:
                                potential_path = extract_path / pattern
                                if potential_path.exists() and (potential_path / "mini_dev_sqlite.json").exists():
                                    mini_dev_data = potential_path
                                    logger.info(f"Found data at: {pattern}")
                                    break

                            if mini_dev_data is None:
                                logger.error("mini_dev_sqlite.json not found in expected locations")
                                logger.error("Searched for: minidev/MINIDEV, MINIDEV, mini_dev_data")
                                logger.error("Extracted contents (first 20 items):")
                                for i, item in enumerate(extract_path.rglob("*")):
                                    if i >= 20:
                                        logger.error("  ... (truncated)")
                                        break
                                    logger.error(f"  - {item.relative_to(extract_path)}")
                                raise FileNotFoundError(
                                    "Data directory with mini_dev_sqlite.json not found in downloaded package"
                                )

                            # Copy files to bird_dir
                            for item in ["mini_dev_sqlite.json", "dev_gold.sql"]:
                                src = mini_dev_data / item
                                if src.exists():
                                    shutil.copy2(src, bird_dir / item)

                            # Copy databases directory
                            src_dbs = mini_dev_data / "dev_databases"
                            if src_dbs.exists():
                                dst_dbs = bird_dir / "dev_databases"
                                if dst_dbs.exists():
                                    shutil.rmtree(dst_dbs)
                                shutil.copytree(src_dbs, dst_dbs)

            finally:
                # Clean up temporary file
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)

            # Verify download succeeded
            if not questions_file.exists():
                raise FileNotFoundError(
                    f"Download failed - mini_dev_sqlite.json not found at {questions_file}"
                )

            logger.info("BIRD Mini-Dev downloaded to %s", bird_dir)

        except Exception as exc:
            logger.error("Download failed: %s", exc)
            raise

    def get_connection_map(self, data_dir: Path) -> Dict[str, str]:
        """Build a ``{db_id: connection_url}`` mapping for all databases."""
        bird_dir = data_dir / "bird-mini-dev" / "dev_databases"
        conn_map: Dict[str, str] = {}
        if not bird_dir.exists():
            return conn_map
        for db_dir in sorted(bird_dir.iterdir()):
            if not db_dir.is_dir():
                continue
            db_file = db_dir / f"{db_dir.name}.sqlite"
            if db_file.exists():
                conn_map[db_dir.name] = f"sqlite:///{db_file}"
        return conn_map

    # ------------------------------------------------------------------
    # Schema extraction
    # ------------------------------------------------------------------

    def _extract_schema(self, bird_dir: Path, db_id: str) -> str:
        """Extract CREATE TABLE statements from a BIRD SQLite database."""
        if db_id in self._schema_cache:
            return self._schema_cache[db_id]

        db_path = bird_dir / "dev_databases" / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            return ""

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND sql IS NOT NULL"
            )
            statements = [row[0] for row in cursor.fetchall()]

            parts = []
            for stmt in statements:
                table_name = (
                    stmt.split("(")[0]
                    .replace("CREATE TABLE", "")
                    .strip()
                    .strip("\"'`")
                )
                try:
                    cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                    count = cursor.fetchone()[0]
                    parts.append(f"{stmt};\n-- {count} rows")
                except Exception:
                    parts.append(f"{stmt};")

            conn.close()
            schema = "\n\n".join(parts)
            self._schema_cache[db_id] = schema
            return schema
        except Exception as exc:
            logger.warning("Schema extraction failed for %s: %s", db_id, exc)
            return ""
