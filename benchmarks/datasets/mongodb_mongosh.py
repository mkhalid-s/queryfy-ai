"""
MongoDB NL-to-Mongosh Dataset Loader

Loads the 766-case MongoDB benchmark from HuggingFace.
Each case maps a natural-language query to an expected mongosh command
across 8 MongoDB Atlas sample databases.

Source: https://huggingface.co/datasets/mongodb-eai/natural-language-to-mongosh
"""

from __future__ import annotations

import csv
import io
import json
import logging
import ssl
import urllib.request
from pathlib import Path
from typing import List

from benchmarks.core.dataset import BenchmarkDataset
from benchmarks.core.types import BenchmarkCase, DatabaseCategory, Difficulty

logger = logging.getLogger(__name__)

DATASET_CSV_URL = (
    "https://huggingface.co/datasets/mongodb-eai/natural-language-to-mongosh"
    "/resolve/main/atlas_sample_data_benchmark.braintrust.csv"
)

_COMPLEXITY_MAP = {
    "simple": Difficulty.SIMPLE,
    "moderate": Difficulty.MODERATE,
    "complex": Difficulty.CHALLENGING,
}


class MongoDBMongoshDataset(BenchmarkDataset):
    NAME = "mongodb-nl-to-mongosh"
    DESCRIPTION = "766 NL-to-mongosh cases across 8 MongoDB Atlas sample databases"
    DB_TYPE = DatabaseCategory.NOSQL_DOCUMENT
    SOURCE_URL = DATASET_CSV_URL
    TOTAL_CASES = 766

    def load(self, data_dir: Path) -> List[BenchmarkCase]:
        """Load benchmark cases from the cached CSV file.

        Expected layout::

            data_dir/mongodb-mongosh/benchmark.csv
        """
        csv_path = data_dir / "mongodb-mongosh" / "benchmark.csv"
        if not csv_path.exists():
            raise FileNotFoundError(
                f"MongoDB benchmark CSV not found at {csv_path}. "
                f"Run download() first."
            )

        content = csv_path.read_text(encoding="utf-8")
        return self._parse_csv(content)

    def download(self, data_dir: Path) -> None:
        """Download the benchmark CSV from HuggingFace."""
        csv_dir = data_dir / "mongodb-mongosh"
        csv_path = csv_dir / "benchmark.csv"

        if csv_path.exists():
            logger.info("MongoDB benchmark already cached at %s", csv_path)
            return

        csv_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading MongoDB benchmark from %s", DATASET_CSV_URL)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(DATASET_CSV_URL, context=ctx) as resp:
            content = resp.read().decode("utf-8")

        csv_path.write_text(content, encoding="utf-8")
        logger.info("Saved %d bytes to %s", len(content), csv_path)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_csv(self, content: str) -> List[BenchmarkCase]:
        """Parse the braintrust-format CSV into BenchmarkCase instances."""
        reader = csv.DictReader(io.StringIO(content))
        cases: List[BenchmarkCase] = []

        for idx, row in enumerate(reader):
            try:
                input_data = json.loads(row["input"])
                expected_data = json.loads(row["expected"])
                metadata = json.loads(row.get("metadata", "{}"))
                tags = json.loads(row.get("tags", "[]"))
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Skipping malformed row %d: %s", idx, exc)
                continue

            db_name = input_data.get("databaseName", "unknown")
            complexity = metadata.get("complexity", "simple")
            difficulty = _COMPLEXITY_MAP.get(complexity, Difficulty.SIMPLE)
            operators = metadata.get("queryOperators", [])
            methods = metadata.get("methods", [])
            collection = expected_data.get("collectionName", "")

            cases.append(
                BenchmarkCase(
                    case_id=row.get("id", f"mongo_{idx}"),
                    natural_language=input_data.get("nlQuery", ""),
                    gold_query=expected_data.get("dbQuery", ""),
                    db_name=db_name,
                    db_type=DatabaseCategory.NOSQL_DOCUMENT,
                    difficulty=difficulty,
                    collection_name=collection,
                    operators=operators,
                    tags=tags + methods,
                )
            )

        logger.info("Parsed %d MongoDB benchmark cases", len(cases))
        return cases
