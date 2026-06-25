"""
QueryfyAI - Base Schema Extractor

Template Method Pattern for database schema extraction.
Defines the algorithm structure in the base class,
with subclasses implementing database-specific steps.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, AsyncContextManager, Dict, List, Optional

logger = logging.getLogger(__name__)


class SchemaExtractor(ABC):
    """
    Abstract base class for schema extraction using Template Method pattern.

    The template method `extract()` defines the algorithm:
    1. Initialize schema structure
    2. Connect to database
    3. Extract tables
    4. For each table: extract columns, primary keys, foreign keys
    5. Extract views
    6. Return schema

    Subclasses implement the database-specific abstract methods.
    """

    # Override in subclasses - schemas to exclude from extraction
    SYSTEM_SCHEMAS: List[str] = []

    # Database type identifier
    DB_TYPE: str = ""

    # =========================================================================
    # Sampling Constants (Single Source of Truth)
    # Used by NoSQL extractors for value sampling to ensure consistency
    # =========================================================================
    MAX_FIELDS_TO_SAMPLE: int = 20  # Maximum fields to sample per table
    MAX_DISTINCT_VALUES: int = 25  # Maximum distinct values to fetch per field
    MIN_CARDINALITY: int = 1  # Minimum distinct values for low-cardinality
    MAX_CARDINALITY: int = 20  # Maximum distinct values for low-cardinality

    def _is_low_cardinality(self, values: List[str]) -> bool:
        """
        Check if values represent a low-cardinality field.

        Low-cardinality fields (1 < count <= 20) are good candidates for
        sample values that help LLMs generate accurate queries.

        Args:
            values: List of distinct values

        Returns:
            True if field is low-cardinality
        """
        return self.MIN_CARDINALITY < len(values) <= self.MAX_CARDINALITY

    async def extract(self, connection_url: str) -> Dict[str, Any]:
        """
        Template method - defines the schema extraction algorithm.

        This method orchestrates the extraction process.
        Subclasses implement the abstract methods for database-specific logic.

        Args:
            connection_url: Database connection string

        Returns:
            Schema dictionary with tables, columns, keys, and views
        """
        schema = self._initialize_schema()

        try:
            logger.info(f"Extracting schema for {self.DB_TYPE}...")

            async with self._get_connection(connection_url) as conn:
                # Step 1: Get all tables
                tables = await self._get_tables(conn)
                logger.info(f"Found {len(tables)} tables")

                # Step 2: For each table, extract metadata
                for table_name, table_schema in tables:
                    table_info = {
                        "name": table_name,
                        "schema": table_schema,
                        "columns": [],
                        "primary_keys": [],
                        "foreign_keys": [],
                        "row_count_estimate": None,
                    }

                    # Get columns
                    table_info["columns"] = await self._get_columns(
                        conn, table_name, table_schema
                    )

                    # Get primary keys (optional)
                    try:
                        table_info["primary_keys"] = await self._get_primary_keys(
                            conn, table_name, table_schema
                        )
                    except Exception as e:
                        logger.debug(
                            f"Failed to get primary keys for {table_name}: {e}"
                        )

                    # Get foreign keys (optional)
                    try:
                        table_info["foreign_keys"] = await self._get_foreign_keys(
                            conn, table_name, table_schema
                        )
                    except Exception as e:
                        logger.debug(
                            f"Failed to get foreign keys for {table_name}: {e}"
                        )

                    # Get row count estimate (optional)
                    try:
                        table_info["row_count_estimate"] = (
                            await self._get_row_count_estimate(
                                conn, table_name, table_schema
                            )
                        )
                    except Exception as e:
                        logger.debug(f"Failed to get row count for {table_name}: {e}")

                    schema["tables"].append(table_info)

                # Step 3: Get views
                try:
                    schema["views"] = await self._get_views(conn)
                    logger.info(f"Found {len(schema['views'])} views")
                except Exception as e:
                    logger.debug(f"Failed to get views: {e}")

            schema["extracted_at"] = datetime.now().isoformat()
            logger.info(
                f"Schema extraction complete: {len(schema['tables'])} tables, {len(schema.get('views', []))} views"
            )

            return schema

        except Exception as e:
            logger.error(f"Schema extraction failed: {e}")
            return {
                "db_type": self.DB_TYPE,
                "tables": [],
                "views": [],
                "collections": [],
                "error": str(e),
                "extracted_at": datetime.now().isoformat(),
            }

    def _initialize_schema(self) -> Dict[str, Any]:
        """Initialize the schema structure."""
        return {
            "db_type": self.DB_TYPE,
            "tables": [],
            "views": [],
            "collections": [],  # For MongoDB
            "extracted_at": None,
        }

    @abstractmethod
    def _get_connection(self, connection_url: str) -> AsyncContextManager[Any]:
        """
        Get database connection context manager.
        Must return an async context manager.
        Implementations should use @asynccontextmanager decorator.
        """
        pass

    @abstractmethod
    async def _get_tables(self, conn) -> List[tuple]:
        """
        Get list of tables.

        Returns:
            List of (table_name, schema_name) tuples
        """
        pass

    @abstractmethod
    async def _get_columns(self, conn, table: str, schema: str) -> List[Dict[str, Any]]:
        """
        Get columns for a table.

        Returns:
            List of column dictionaries with: name, type, nullable, default
        """
        pass

    async def _get_primary_keys(self, conn, table: str, schema: str) -> List[str]:
        """
        Get primary key columns for a table.
        Override in subclasses that support primary key extraction.

        Returns:
            List of primary key column names
        """
        return []

    async def _get_foreign_keys(
        self, conn, table: str, schema: str
    ) -> List[Dict[str, Any]]:
        """
        Get foreign key constraints for a table.
        Override in subclasses that support foreign key extraction.

        Returns:
            List of foreign key dictionaries with: column, references_table, references_column
        """
        return []

    async def _get_views(self, conn) -> List[Dict[str, Any]]:
        """
        Get list of views.
        Override in subclasses that support view extraction.

        Returns:
            List of view dictionaries with: name, schema
        """
        return []

    async def _get_row_count_estimate(
        self, conn, table: str, schema: str
    ) -> Optional[int]:
        """
        Get estimated row count for a table.
        Override in subclasses that support row count estimation.

        Returns:
            Estimated row count or None
        """
        return None


class MongoDBSchemaExtractor(SchemaExtractor):
    """
    Special base class for MongoDB schema extraction.

    MongoDB doesn't have a fixed schema, so this extracts
    collection names and sample document structures.
    """

    DB_TYPE = "mongodb"
    SYSTEM_DATABASES: List[str] = ["admin", "local", "config"]

    async def extract(self, connection_url: str) -> Dict[str, Any]:
        """
        Extract MongoDB schema (collections and sample documents).
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

                for collection_name in collections:
                    # Skip system collections
                    if collection_name.startswith("system."):
                        continue

                    collection_info = {
                        "name": collection_name,
                        "fields": [],
                        "sample_count": 0,
                    }

                    # Get sample documents to infer schema
                    collection = db[collection_name]
                    cursor = collection.find({}).limit(10)
                    samples = []
                    async for doc in cursor:
                        samples.append(doc)

                    if samples:
                        collection_info["sample_count"] = len(samples)
                        collection_info["fields"] = self._infer_fields(samples)

                    # Get estimated count
                    try:
                        collection_info["estimated_count"] = (
                            await collection.estimated_document_count()
                        )
                    except Exception as e:
                        logger.debug(
                            f"Could not get estimated count for collection: {e}"
                        )
                        collection_info["estimated_count"] = None

                    schema["collections"].append(collection_info)

            schema["extracted_at"] = datetime.now().isoformat()
            logger.info(
                f"MongoDB schema extraction complete: {len(schema['collections'])} collections"
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

    def _infer_fields(self, samples: List[Dict]) -> List[Dict[str, Any]]:
        """Infer field types from sample documents."""
        fields = {}

        for doc in samples:
            for key, value in doc.items():
                if key not in fields:
                    fields[key] = {
                        "name": key,
                        "type": self._get_mongo_type(value),
                        "nullable": False,
                    }
                # Check for null values
                if value is None:
                    fields[key]["nullable"] = True

        return list(fields.values())

    def _get_mongo_type(self, value) -> str:
        """
        Get MongoDB type string from Python value.

        Handles all BSON types for accurate schema representation.
        """
        from datetime import date, datetime
        from decimal import Decimal

        if value is None:
            return "Null"

        # Get type name for BSON type checking
        type_name = type(value).__name__

        # BSON-specific types (check by type name to avoid import issues)
        if type_name == "ObjectId":
            return "ObjectId"
        elif type_name == "Timestamp":
            return "Timestamp"
        elif type_name == "Decimal128":
            return "Decimal128"
        elif type_name == "Binary":
            return "BinData"
        elif type_name == "Regex":
            return "Regex"
        elif type_name == "Code":
            return "Code"
        elif type_name == "MinKey":
            return "MinKey"
        elif type_name == "MaxKey":
            return "MaxKey"
        elif type_name == "DBRef":
            return "DBRef"
        elif type_name == "Int64":
            return "Int64"
        elif type_name == "UUID":
            return "UUID"
        # Standard Python types
        elif isinstance(value, bool):  # Must check before int (bool is subclass of int)
            return "Boolean"
        elif isinstance(value, int):
            return "Int32"
        elif isinstance(value, float):
            return "Double"
        elif isinstance(value, str):
            return "String"
        elif isinstance(value, datetime):
            return "Date"
        elif isinstance(value, date):
            return "Date"
        elif isinstance(value, bytes):
            return "BinData"
        elif isinstance(value, Decimal):
            return "Decimal128"
        elif isinstance(value, list):
            return "Array"
        elif isinstance(value, dict):
            return "Object"
        else:
            return type_name

    @abstractmethod
    def _get_connection(self, connection_url: str):
        """Get MongoDB client context manager. Should use @asynccontextmanager."""
        pass

    async def _get_tables(self, conn) -> List[tuple]:
        """MongoDB doesn't have tables."""
        return []

    async def _get_columns(self, conn, table: str, schema: str) -> List[Dict[str, Any]]:
        """MongoDB doesn't have columns."""
        return []
