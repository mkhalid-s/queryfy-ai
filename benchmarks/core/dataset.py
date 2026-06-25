"""
QueryfyAI Benchmarks - Dataset Abstract Base Class

Defines the contract that every benchmark dataset adapter must implement.
Concrete implementations (e.g., Spider, BIRD, NoSQL-Bench) inherit from
``BenchmarkDataset`` and supply ``load`` and ``download`` logic.
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Sequence

from benchmarks.core.types import BenchmarkCase, DatabaseCategory, Difficulty

logger = logging.getLogger(__name__)


class BenchmarkDataset(ABC):
    """Abstract interface for loading and filtering benchmark datasets.

    Class Attributes:
        NAME: Short machine-readable identifier (e.g., ``"spider"``).
        DESCRIPTION: Human-readable one-liner for CLI / report output.
        DB_TYPE: The :class:`DatabaseCategory` this dataset targets.
        SOURCE_URL: Canonical download URL for the raw data.
        TOTAL_CASES: Expected case count for the *full* dataset.  Used for
            progress reporting and sanity-checking after load.
    """

    NAME: str = ""
    DESCRIPTION: str = ""
    DB_TYPE: DatabaseCategory = DatabaseCategory.SQL
    SOURCE_URL: str = ""
    TOTAL_CASES: int = 0

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    def load(self, data_dir: Path) -> List[BenchmarkCase]:
        """Load benchmark cases from previously-downloaded data.

        Args:
            data_dir: Root directory containing the dataset files.

        Returns:
            Complete list of benchmark cases.

        Raises:
            FileNotFoundError: When expected data files are missing.
                Call :meth:`download` first in that case.
            ValueError: When the data files are malformed.
        """

    @abstractmethod
    def download(self, data_dir: Path) -> None:
        """Download / prepare the raw dataset into *data_dir*.

        Implementations should be idempotent: re-running on an already-
        populated directory must not corrupt existing data.

        Args:
            data_dir: Target directory for downloaded files.

        Raises:
            RuntimeError: On network or permission errors.
        """

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def filter_by_difficulty(
        self,
        cases: List[BenchmarkCase],
        difficulties: Sequence[Difficulty],
    ) -> List[BenchmarkCase]:
        """Return only cases whose difficulty is in *difficulties*.

        Args:
            cases: Input case list (not mutated).
            difficulties: Allowed difficulty levels.

        Returns:
            Filtered list preserving original order.
        """
        allowed = set(difficulties)
        filtered = [c for c in cases if c.difficulty in allowed]
        logger.info(
            "Filtered by difficulty %s: %d -> %d cases",
            [d.value for d in difficulties],
            len(cases),
            len(filtered),
        )
        return filtered

    def filter_by_db(
        self,
        cases: List[BenchmarkCase],
        db_names: Sequence[str],
    ) -> List[BenchmarkCase]:
        """Return only cases targeting one of the given database names.

        Comparison is case-insensitive to accommodate mixed-case dataset
        conventions.

        Args:
            cases: Input case list (not mutated).
            db_names: Allowed database names.

        Returns:
            Filtered list preserving original order.
        """
        allowed = {name.lower() for name in db_names}
        filtered = [c for c in cases if c.db_name.lower() in allowed]
        logger.info(
            "Filtered by db_names %s: %d -> %d cases",
            list(db_names),
            len(cases),
            len(filtered),
        )
        return filtered

    def sample(
        self,
        cases: List[BenchmarkCase],
        n: int,
        seed: Optional[int] = None,
    ) -> List[BenchmarkCase]:
        """Return a random sample of *n* cases.

        When *n* >= len(cases) the full list is returned (shuffled).

        Args:
            cases: Input case list (not mutated).
            n: Desired sample size.
            seed: Optional RNG seed for reproducibility.

        Returns:
            Randomly sampled subset.
        """
        rng = random.Random(seed)
        n = min(n, len(cases))
        sampled = rng.sample(cases, n)
        logger.info("Sampled %d cases (seed=%s)", len(sampled), seed)
        return sampled
