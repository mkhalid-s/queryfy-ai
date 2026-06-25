"""
QueryfyAI Benchmarks - Dataset Registry

Maps dataset names to concrete BenchmarkDataset implementations.
"""

from __future__ import annotations

from typing import Dict, Type

from benchmarks.core.dataset import BenchmarkDataset
from benchmarks.datasets.bird import BirdMiniDevDataset
from benchmarks.datasets.cassandra_banking import CassandraBankingDataset
from benchmarks.datasets.dynamodb_logistics import DynamoDBLogisticsDataset
from benchmarks.datasets.mongodb_mongosh import MongoDBMongoshDataset

DATASETS: Dict[str, Type[BenchmarkDataset]] = {
    "bird-mini-dev": BirdMiniDevDataset,
    "mongodb-nl-to-mongosh": MongoDBMongoshDataset,
    "cassandra-banking": CassandraBankingDataset,
    "dynamodb-logistics": DynamoDBLogisticsDataset,
}


def get_dataset(name: str) -> BenchmarkDataset:
    """Instantiate a dataset loader by name."""
    cls = DATASETS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown dataset: {name!r}. Available: {sorted(DATASETS)}"
        )
    return cls()


__all__ = ["DATASETS", "get_dataset"]
