"""
QueryfyAI - MongoDB Schema Extractor

MongoDB-specific implementation of schema extraction.
Infers schema from sample documents since MongoDB is schemaless.
Uses ConnectionPoolManager for efficient connection reuse.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List

from app.models.schemas import DatabaseConfig
from app.services.connection_pool_manager import pool_manager

from .base import MongoDBSchemaExtractor as BaseMongoDBExtractor
from .sensitive_field_mixin import SensitiveFieldMixin

logger = logging.getLogger(__name__)


class MongoDBSchemaExtractor(BaseMongoDBExtractor, SensitiveFieldMixin):
    """MongoDB schema extractor using motor (async pymongo)."""

    DB_TYPE = "mongodb"
    SYSTEM_DATABASES = ["admin", "local", "config"]

    @asynccontextmanager
    async def _get_connection(self, connection_url: str):
        """Get MongoDB client from pool manager."""
        config = DatabaseConfig(db_type="mongodb", connection_url=connection_url)
        async with pool_manager.get_connection(config) as client:
            yield client

    async def extract(self, connection_url: str) -> Dict[str, Any]:
        """
        Extract MongoDB schema (collections and inferred fields).
        """
        schema: Dict[str, Any] = {
            "db_type": "mongodb",
            "tables": [],
            "views": [],
            "collections": [],
            "extracted_at": None,
        }

        try:
            logger.info("Extracting MongoDB schema...")

            async with self._get_connection(connection_url) as client:
                # Extract database name from URL
                from urllib.parse import urlparse

                parsed = urlparse(connection_url)
                db_name = parsed.path.lstrip("/").split("?")[0]

                if not db_name:
                    logger.warning("No database name in MongoDB URL")
                    schema["error"] = "Database name not specified in connection URL"
                    return schema

                db = client[db_name]
                collections = await db.list_collection_names()

                collections_list: List[Dict[str, Any]] = []
                for collection_name in collections:
                    # Skip system collections
                    if collection_name.startswith("system."):
                        continue

                    collection_info = await self._extract_collection_schema(
                        db, collection_name
                    )
                    collections_list.append(collection_info)

                schema["collections"] = collections_list

            schema["extracted_at"] = datetime.now().isoformat()
            logger.info(
                f"MongoDB schema extraction complete: {len(collections_list)} collections"
            )

            return schema

        except Exception as e:
            logger.error(f"MongoDB schema extraction failed: {e}")
            return {
                "db_type": "mongodb",
                "tables": [],
                "views": [],
                "collections": [],
                "error": str(e),
                "extracted_at": datetime.now().isoformat(),
            }

    async def _extract_collection_schema(
        self, db, collection_name: str
    ) -> Dict[str, Any]:
        """Extract schema for a single collection."""
        collection = db[collection_name]

        collection_info = {
            "name": collection_name,
            "fields": [],
            "sample_count": 0,
            "estimated_count": None,
            "indexes": [],
        }

        # Get sample documents to infer schema
        cursor = collection.find({}).limit(100)
        samples = []
        async for doc in cursor:
            samples.append(doc)

        if samples:
            collection_info["sample_count"] = len(samples)
            fields_list = self._infer_fields_deep(samples)
            collection_info["fields"] = fields_list

            # Sample values for low-cardinality string fields
            try:
                await self._sample_field_values(collection, fields_list)
            except Exception as e:
                logger.debug(f"Could not sample field values: {e}")

        # Get estimated count
        try:
            collection_info["estimated_count"] = (
                await collection.estimated_document_count()
            )
        except Exception as e:
            logger.debug(f"Could not get estimated count: {e}")

        # Get indexes
        try:
            indexes = await collection.index_information()
            collection_info["indexes"] = [
                {"name": name, "keys": list(info.get("key", []))}
                for name, info in indexes.items()
            ]
        except Exception as e:
            logger.debug(f"Could not get index information: {e}")

        return collection_info

    def _infer_fields_deep(
        self, samples: List[Dict], prefix: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Infer field types from sample documents.
        Handles nested documents with dot notation.
        """
        fields: Dict[str, Dict[str, Any]] = {}
        null_counts: Dict[str, int] = {}
        total = len(samples)

        for doc in samples:
            self._process_document(doc, fields, null_counts, prefix)

        # Convert to list and add nullable info
        result = []
        for field_path, field_info in fields.items():
            null_count = null_counts.get(field_path, 0)
            field_info["nullable"] = null_count > 0 or null_count < total
            result.append(field_info)

        # Sort by field name
        result.sort(key=lambda x: x["name"])
        return result

    def _process_document(
        self, doc: Dict, fields: Dict, null_counts: Dict, prefix: str = ""
    ):
        """Process a document and extract field information."""
        for key, value in doc.items():
            field_path = f"{prefix}{key}" if prefix else key

            if field_path not in fields:
                fields[field_path] = {
                    "name": field_path,
                    "type": self._get_mongo_type(value),
                    "nullable": False,
                }
                null_counts[field_path] = 0

            if value is None:
                null_counts[field_path] = null_counts.get(field_path, 0) + 1

            # Recursively process nested documents (limit depth to avoid too many fields)
            if isinstance(value, dict) and not field_path.count(".") >= 2:
                self._process_document(value, fields, null_counts, f"{field_path}.")

    async def _sample_field_values(
        self, collection, fields: List[Dict[str, Any]]
    ) -> None:
        """
        Sample distinct values for low-cardinality string fields.

        Modifies fields in place to add sample_values.
        Uses base class constants for consistency across extractors.

        SECURITY: Skips sensitive fields (password, token, email, etc.)
        """
        fields_sampled = 0
        for field in fields:
            if fields_sampled >= self.MAX_FIELDS_TO_SAMPLE:
                break

            field_name = field["name"]
            field_type = field["type"]

            # Only sample String fields
            if field_type != "String":
                continue

            # Skip sensitive fields (from SensitiveFieldMixin)
            if self._is_sensitive_field(field_name):
                continue

            # Skip nested fields (too complex for aggregation)
            if "." in field_name:
                continue

            try:
                # Use aggregation to get distinct values
                # Filter: field must exist, be a string type, and not be empty
                pipeline = [
                    {
                        "$match": {
                            field_name: {
                                "$exists": True,
                                "$type": "string",
                                "$ne": "",  # Exclude empty strings
                            }
                        }
                    },
                    {"$group": {"_id": f"${field_name}"}},
                    {"$limit": self.MAX_DISTINCT_VALUES},
                ]
                cursor = collection.aggregate(pipeline)
                values = []
                async for doc in cursor:
                    if doc["_id"] is not None and doc["_id"] != "":
                        values.append(str(doc["_id"]))

                # Only keep if low-cardinality (uses base class method)
                if self._is_low_cardinality(values):
                    field["sample_values"] = values
                    fields_sampled += 1

            except Exception as e:
                logger.debug(f"Could not sample values for {field_name}: {e}")
