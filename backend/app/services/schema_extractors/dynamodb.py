"""
QueryfyAI - DynamoDB Schema Extractor

DynamoDB-specific implementation of schema extraction.
Uses AWS SDK to describe tables, get key schemas, and sample items for attribute inference.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from .base import SchemaExtractor
from .sensitive_field_mixin import SensitiveFieldMixin

logger = logging.getLogger(__name__)


class DynamoDBSchemaExtractor(SchemaExtractor, SensitiveFieldMixin):
    """
    DynamoDB schema extractor using boto3/aioboto3.

    Extracts:
    - Table names
    - Key schema (partition key, sort key)
    - Attribute definitions
    - Global Secondary Indexes (GSI)
    - Local Secondary Indexes (LSI)
    - Sampled attributes from actual data
    """

    DB_TYPE = "dynamodb"
    SYSTEM_KEYSPACES: List[str] = []  # DynamoDB doesn't have system keyspaces

    def _parse_connection_url(self, url: str) -> Dict[str, Any]:
        """
        Parse DynamoDB connection URL.

        Formats:
        - dynamodb://region/                        (uses default AWS credentials)
        - dynamodb://access_key:secret@region/      (explicit credentials)
        - dynamodb://localhost:8000/                (local DynamoDB)
        """
        from urllib.parse import unquote, urlparse

        parsed = urlparse(url)

        # Check if it's a local endpoint (has port)
        if parsed.port:
            return {
                "endpoint_url": f"http://{parsed.hostname}:{parsed.port}",
                "region": "local",
                "access_key": parsed.username,
                "secret_key": unquote(parsed.password) if parsed.password else None,
            }

        # AWS DynamoDB
        return {
            "endpoint_url": None,
            "region": parsed.hostname or "us-east-1",
            "access_key": parsed.username,
            "secret_key": unquote(parsed.password) if parsed.password else None,
        }

    @asynccontextmanager
    async def _get_connection(self, connection_url: str):
        """
        Get DynamoDB client using aioboto3.
        """
        import aioboto3

        params = self._parse_connection_url(connection_url)
        session = aioboto3.Session()

        client_kwargs = {}
        if params["region"] and params["region"] != "local":
            client_kwargs["region_name"] = params["region"]
        if params["endpoint_url"]:
            client_kwargs["endpoint_url"] = params["endpoint_url"]
        if params["access_key"] and params["secret_key"]:
            client_kwargs["aws_access_key_id"] = params["access_key"]
            client_kwargs["aws_secret_access_key"] = params["secret_key"]

        async with session.client("dynamodb", **client_kwargs) as client:
            yield client

    async def _list_tables(self, client) -> List[str]:
        """List all tables in the DynamoDB instance."""
        tables = []
        paginator = client.get_paginator("list_tables")

        async for page in paginator.paginate():
            tables.extend(page.get("TableNames", []))

        return tables

    async def _describe_table(self, client, table_name: str) -> Dict[str, Any]:
        """Get detailed table metadata."""
        response = await client.describe_table(TableName=table_name)
        return response.get("Table", {})

    async def _sample_items(
        self, client, table_name: str, limit: int = 50
    ) -> List[Dict]:
        """
        Sample items from a table to infer attribute types.

        DynamoDB doesn't have a schema, so we sample actual items
        to understand the attribute structure.

        Note: Increased from 10 to 50 items for better attribute coverage.
        """
        try:
            response = await client.scan(TableName=table_name, Limit=limit)
            return response.get("Items", [])
        except Exception as e:
            logger.debug(f"Could not sample items from {table_name}: {e}")
            return []

    def _get_dynamodb_type(self, type_code: str) -> str:
        """Convert DynamoDB type code to human-readable type."""
        type_map = {
            "S": "String",
            "N": "Number",
            "B": "Binary",
            "SS": "String Set",
            "NS": "Number Set",
            "BS": "Binary Set",
            "M": "Map",
            "L": "List",
            "BOOL": "Boolean",
            "NULL": "Null",
        }
        return type_map.get(type_code, type_code)

    def _extract_dynamodb_attribute(self, attr_value: Dict) -> Optional[tuple]:
        """
        Extract type code and value from DynamoDB attribute format.

        DynamoDB attributes have format: {"S": "value"} or {"N": "123"}
        Returns (type_code, actual_value) or None if invalid format.
        """
        if not isinstance(attr_value, dict) or len(attr_value) != 1:
            return None
        # DynamoDB format guarantees single key-value pair
        type_code, actual_value = next(iter(attr_value.items()))
        return type_code, actual_value

    def _infer_attributes_from_sample(self, items: List[Dict]) -> List[Dict[str, Any]]:
        """
        Infer attribute names, types, and sample values from sample items.

        Design Pattern: Template Method - separates attribute extraction
        from sample value collection for cleaner code.

        Extracts sample values for low-cardinality String attributes
        to help LLM generate accurate queries.
        """
        attributes: Dict[str, Dict[str, Any]] = {}
        # Track distinct values for each string attribute (for sampling)
        string_values: Dict[str, set] = {}

        for item in items:
            for attr_name, attr_value in item.items():
                # Skip sensitive fields early (performance optimization)
                if self._is_sensitive_field(attr_name):
                    # Still track the attribute but don't sample values
                    if attr_name not in attributes:
                        extracted = self._extract_dynamodb_attribute(attr_value)
                        if extracted:
                            type_code, _ = extracted
                            attributes[attr_name] = {
                                "name": attr_name,
                                "type": self._get_dynamodb_type(type_code),
                                "nullable": True,
                            }
                    continue

                # Extract type and value from DynamoDB format
                extracted = self._extract_dynamodb_attribute(attr_value)
                if not extracted:
                    continue

                type_code, actual_value = extracted

                # Initialize attribute if first occurrence
                if attr_name not in attributes:
                    attributes[attr_name] = {
                        "name": attr_name,
                        "type": self._get_dynamodb_type(type_code),
                        "nullable": True,
                    }
                    # Initialize value tracking for strings
                    if type_code == "S":
                        string_values[attr_name] = set()

                # Collect string values for sampling (uses base class constant)
                if type_code == "S" and attr_name in string_values:
                    if len(string_values[attr_name]) < self.MAX_DISTINCT_VALUES:
                        string_values[attr_name].add(str(actual_value))

        # Add sample values for low-cardinality string attributes
        result = list(attributes.values())
        for attr in result:
            attr_name = attr["name"]
            if attr_name in string_values:
                values = list(string_values[attr_name])
                # Only include if low-cardinality (uses base class method)
                if self._is_low_cardinality(values):
                    attr["sample_values"] = values

        return result

    async def _get_tables(self, client) -> List[tuple]:
        """
        Get all tables.

        Returns:
            List of (table_name, 'default') tuples (DynamoDB doesn't have schemas)
        """
        table_names = await self._list_tables(client)
        return [(name, "default") for name in table_names]

    async def _get_columns(
        self, client, table: str, schema: str
    ) -> List[Dict[str, Any]]:
        """
        Get columns (attributes) for a table.

        Combines key schema definitions with sampled attributes.
        """
        # Get table description for key schema
        table_desc = await self._describe_table(client, table)

        columns = []
        key_attrs = {}

        # Get key schema
        key_schema = table_desc.get("KeySchema", [])
        attr_definitions = {
            attr["AttributeName"]: attr["AttributeType"]
            for attr in table_desc.get("AttributeDefinitions", [])
        }

        for key in key_schema:
            attr_name = key["AttributeName"]
            key_type = key["KeyType"]  # HASH or RANGE
            attr_type = attr_definitions.get(attr_name, "S")

            col = {
                "name": attr_name,
                "type": self._get_dynamodb_type(attr_type),
                "nullable": False,  # Keys are always required
                "key_type": "PARTITION" if key_type == "HASH" else "SORT",
            }

            # Add helpful comments for LLM
            if key_type == "HASH":
                col["comment"] = "PARTITION KEY - Required in WHERE clause"
            else:
                col["comment"] = "SORT KEY - Use for range queries"

            columns.append(col)
            key_attrs[attr_name] = True

        # Sample items to discover additional attributes
        samples = await self._sample_items(client, table)
        inferred = self._infer_attributes_from_sample(samples)

        # Add non-key attributes
        for attr in inferred:
            if attr["name"] not in key_attrs:
                columns.append(attr)

        return columns

    async def _get_primary_keys(self, client, table: str, schema: str) -> List[str]:
        """Get primary key attribute names."""
        table_desc = await self._describe_table(client, table)
        key_schema = table_desc.get("KeySchema", [])

        # Return partition key first, then sort key
        partition_keys = [
            k["AttributeName"] for k in key_schema if k["KeyType"] == "HASH"
        ]
        sort_keys = [k["AttributeName"] for k in key_schema if k["KeyType"] == "RANGE"]

        return partition_keys + sort_keys

    async def _get_indexes(self, client, table: str) -> Dict[str, List[Dict]]:
        """Get Global and Local Secondary Indexes."""
        table_desc = await self._describe_table(client, table)

        gsi = []
        for index in table_desc.get("GlobalSecondaryIndexes", []):
            idx_info = {
                "name": index["IndexName"],
                "type": "GSI",
                "keys": [],
                "projection": index.get("Projection", {}).get("ProjectionType", "ALL"),
            }
            for key in index.get("KeySchema", []):
                idx_info["keys"].append(
                    {
                        "name": key["AttributeName"],
                        "key_type": "PARTITION" if key["KeyType"] == "HASH" else "SORT",
                    }
                )
            gsi.append(idx_info)

        lsi = []
        for index in table_desc.get("LocalSecondaryIndexes", []):
            idx_info = {
                "name": index["IndexName"],
                "type": "LSI",
                "keys": [],
                "projection": index.get("Projection", {}).get("ProjectionType", "ALL"),
            }
            for key in index.get("KeySchema", []):
                idx_info["keys"].append(
                    {
                        "name": key["AttributeName"],
                        "key_type": "PARTITION" if key["KeyType"] == "HASH" else "SORT",
                    }
                )
            lsi.append(idx_info)

        return {"gsi": gsi, "lsi": lsi}

    async def _get_row_count_estimate(
        self, client, table: str, schema: str
    ) -> Optional[int]:
        """Get estimated item count from table description."""
        table_desc = await self._describe_table(client, table)
        return table_desc.get("ItemCount")

    async def extract(self, connection_url: str) -> Dict[str, Any]:
        """
        Extract DynamoDB schema with additional metadata.

        Extends base extraction to include:
        - Partition and sort key information
        - Global Secondary Indexes (GSI)
        - Local Secondary Indexes (LSI)
        - Sampled attributes
        """
        schema = self._initialize_schema()

        try:
            logger.info(f"Extracting schema for {self.DB_TYPE}...")

            async with self._get_connection(connection_url) as client:
                # Get all tables
                tables = await self._get_tables(client)
                logger.info(f"Found {len(tables)} tables")

                # For each table, extract metadata
                for table_name, _ in tables:
                    table_info = {
                        "name": table_name,
                        "schema": "default",  # DynamoDB doesn't have schemas
                        "columns": [],
                        "primary_keys": [],
                        "partition_key": None,
                        "sort_key": None,
                        "foreign_keys": [],  # DynamoDB doesn't have FKs
                        "gsi": [],
                        "lsi": [],
                        "row_count_estimate": None,
                    }

                    # Get columns (includes key information)
                    columns = await self._get_columns(client, table_name, "default")
                    table_info["columns"] = columns

                    # Extract partition and sort keys from columns
                    for col in columns:
                        if col.get("key_type") == "PARTITION":
                            table_info["partition_key"] = col["name"]
                        elif col.get("key_type") == "SORT":
                            table_info["sort_key"] = col["name"]

                    table_info["primary_keys"] = await self._get_primary_keys(
                        client, table_name, "default"
                    )

                    # Get indexes
                    try:
                        indexes = await self._get_indexes(client, table_name)
                        table_info["gsi"] = indexes["gsi"]
                        table_info["lsi"] = indexes["lsi"]
                    except Exception as e:
                        logger.debug(f"Failed to get indexes for {table_name}: {e}")

                    # Get item count estimate
                    try:
                        table_info["row_count_estimate"] = (
                            await self._get_row_count_estimate(
                                client, table_name, "default"
                            )
                        )
                    except Exception as e:
                        logger.debug(f"Failed to get row count for {table_name}: {e}")

                    schema["tables"].append(table_info)

            from datetime import datetime

            schema["extracted_at"] = datetime.now().isoformat()
            logger.info(f"Schema extraction complete: {len(schema['tables'])} tables")

            return schema

        except Exception as e:
            logger.error(f"Schema extraction failed: {e}")
            from datetime import datetime

            return {
                "db_type": self.DB_TYPE,
                "tables": [],
                "views": [],
                "collections": [],
                "error": str(e),
                "extracted_at": datetime.now().isoformat(),
            }
