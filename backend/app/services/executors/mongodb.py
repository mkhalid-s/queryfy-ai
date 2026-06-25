"""
QueryfyAI - MongoDB Query Executor

MongoDB executor using motor (async pymongo) with connection pooling.
Handles MongoDB query syntax: db.collection.find({}) and db.collection.aggregate([])
Uses the shared ConnectionPoolManager for efficient connection reuse.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from app.models.schemas import DatabaseConfig
from app.services.connection_pool_manager import pool_manager

from .base import QueryExecutor

logger = logging.getLogger(__name__)


class MongoDBExecutor(QueryExecutor):
    """
    MongoDB query executor using motor.

    Uses the shared ConnectionPoolManager for connection pooling,
    ensuring efficient connection reuse across sessions and tenants.

    DML Support (MongoDB 4.0+):
    - db.collection.insertOne({document})
    - db.collection.updateOne({filter}, {$set: {...}})
    - db.collection.deleteOne({filter})
    """

    DB_TYPE = "mongodb"
    SUPPORTS_ASYNC = True
    SUPPORTS_DML = True
    SUPPORTS_SANDBOX = True  # MongoDB 4.0+ supports transactions

    def _parse_mongodb_query(self, query: str) -> Tuple[str, str, Any]:
        """
        Parse MongoDB query syntax.

        Supports:
        - db.collection.find({...})
        - db.collection.find({...}, {projection})
        - db.collection.find({...}).sort({...}).limit(n)
        - db.collection.aggregate([...])
        - db.collection.findOne({...})

        Returns:
            Tuple of (collection_name, operation, query_args)
        """
        query = query.strip()

        # Handle multiple queries - take only the first one
        if ";\n" in query or "\ndb." in query:
            lines = [
                line.strip()
                for line in query.split("\n")
                if line.strip() and line.strip().startswith("db.")
            ]
            if lines:
                query = lines[0].rstrip(";")
                logger.warning(
                    "Multiple queries detected, executing only the first one"
                )

        # Remove trailing semicolon
        query = query.rstrip(";").strip()

        # First, match the basic structure: db.collection.operation(
        header_pattern = r"db\.(\w+)\.(find|findOne|aggregate)\s*\("
        header_match = re.match(header_pattern, query, re.IGNORECASE)

        if not header_match:
            raise ValueError(
                "Invalid MongoDB query. Use format: db.collection.find({}) "
                "or db.collection.aggregate([])"
            )

        collection_name = header_match.group(1)
        operation = header_match.group(2).lower()

        # Find the matching closing paren using balanced paren counting
        # This handles method chaining like .find({}).sort({}).limit(10)
        args_start = header_match.end()  # Position after opening (
        args_str = self._extract_balanced_args(query[args_start:])

        # Parse the arguments - handle multiple args like find({}, {projection})
        try:
            if args_str:
                query_args = self._parse_query_args(args_str, operation)
            else:
                query_args = {} if operation != "aggregate" else []
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid query arguments: {e}")

        return collection_name, operation, query_args

    def _extract_balanced_args(self, s: str) -> str:
        """
        Extract arguments from a string, finding the matching closing paren.
        Handles nested braces/brackets and strings with parens inside.

        For input: '{}, {"a": 1}).sort({"b": -1}).limit(10)'
        Returns: '{}, {"a": 1}'
        """
        depth = 1  # We're already past the opening (
        in_string = False
        string_char = None
        i = 0

        while i < len(s) and depth > 0:
            char = s[i]

            # Handle string boundaries
            if char in "\"'":
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char and (i == 0 or s[i - 1] != "\\"):
                    in_string = False
                    string_char = None
            elif not in_string:
                # Only count parens outside of strings
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1

            i += 1

        # Return everything up to (not including) the matching closing paren
        if depth == 0:
            return s[: i - 1].strip()
        else:
            # Unbalanced parens - return everything
            return s.strip()

    def _parse_extended_json(self, json_str: str) -> Any:
        """
        Parse Extended JSON string to Python objects with BSON types.

        Uses bson.json_util.loads() which handles all Extended JSON types:
        - {"$oid": "..."} -> ObjectId
        - {"$date": "..."} -> datetime
        - {"$timestamp": {...}} -> Timestamp
        - {"$numberLong": "..."} -> int64
        - {"$numberDecimal": "..."} -> Decimal128
        - {"$binary": {...}} -> Binary
        - {"$regularExpression": {...}} -> Regex
        - {"$minKey": 1} / {"$maxKey": 1} -> MinKey/MaxKey
        - etc.
        """
        from bson import json_util

        if not json_str or not json_str.strip():
            return {}

        # Use json_util.loads for automatic BSON type conversion
        return json_util.loads(json_str)

    def _parse_query_args(self, args_str: str, operation: str) -> Any:
        """
        Parse query arguments, handling multiple args like find({filter}, {projection}).

        Returns:
            For find/findOne: dict with 'filter' and optional 'projection'
            For aggregate: list (pipeline)
        """
        args_str = args_str.strip()

        # For aggregate, it's always a single array
        if operation == "aggregate":
            normalized = self._normalize_json(args_str)
            return self._parse_extended_json(normalized)

        # For find/findOne, could be single filter or filter + projection
        # Split by top-level comma (not inside braces)
        parts = self._split_args(args_str)

        if len(parts) == 0:
            return {}

        # Parse filter (first argument)
        filter_str = self._normalize_json(parts[0])
        filter_doc = self._parse_extended_json(filter_str) if filter_str else {}

        # Parse projection (second argument) if present
        projection = None
        if len(parts) > 1 and parts[1].strip():
            proj_str = self._normalize_json(parts[1])
            projection = self._parse_extended_json(proj_str)

        # Return as dict with filter and projection
        return {"filter": filter_doc, "projection": projection}

    def _split_args(self, args_str: str) -> List[str]:
        """
        Split arguments by comma, respecting nested braces/brackets.
        """
        parts = []
        current = []
        depth = 0

        for char in args_str:
            if char in "{[":
                depth += 1
                current.append(char)
            elif char in "}]":
                depth -= 1
                current.append(char)
            elif char == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(char)

        if current:
            parts.append("".join(current).strip())

        return parts

    def _normalize_json(self, js_str: str) -> str:
        """
        Normalize JavaScript-style object notation to valid JSON.
        Handles unquoted keys, single quotes, MongoDB operators, and MongoDB-specific types.

        Comprehensive BSON type support:
        - ObjectId, ISODate, new Date, Timestamp
        - NumberLong, NumberInt, NumberDecimal
        - UUID, BinData, Binary
        - Regex patterns (/pattern/flags), RegExp()
        - MinKey, MaxKey, DBRef, Code
        - JavaScript literals (true, false, null, undefined)
        """
        result = js_str.strip()

        # Remove trailing commas before } or ] (common JS syntax that's invalid JSON)
        result = re.sub(r",(\s*[}\]])", r"\1", result)

        # ===== Handle MongoDB-specific types BEFORE other transformations =====

        # ObjectId("...") -> {"$oid": "..."}
        result = re.sub(
            r'ObjectId\s*\(\s*["\']([a-fA-F0-9]{24})["\']\s*\)',
            r'{"$oid": "\1"}',
            result,
        )
        # Handle ObjectId() without quotes (just extract the hex string)
        result = re.sub(
            r"ObjectId\s*\(\s*([a-fA-F0-9]{24})\s*\)", r'{"$oid": "\1"}', result
        )
        # Handle empty ObjectId() - generate placeholder that will be converted
        result = re.sub(
            r"ObjectId\s*\(\s*\)", r'{"$oid": "000000000000000000000000"}', result
        )

        # ISODate("...") -> {"$date": "..."}
        result = re.sub(
            r'ISODate\s*\(\s*["\']([^"\']+)["\']\s*\)', r'{"$date": "\1"}', result
        )
        # ISODate() without parameter -> current date placeholder
        result = re.sub(r"ISODate\s*\(\s*\)", r'{"$date": "$now"}', result)

        # new Date("...") -> {"$date": "..."}
        result = re.sub(
            r'new\s+Date\s*\(\s*["\']([^"\']+)["\']\s*\)', r'{"$date": "\1"}', result
        )
        # new Date() without parameter -> current date placeholder
        result = re.sub(r"new\s+Date\s*\(\s*\)", r'{"$date": "$now"}', result)
        # new Date(milliseconds) -> {"$date": {"$numberLong": "..."}}
        result = re.sub(
            r"new\s+Date\s*\(\s*(\d+)\s*\)", r'{"$date": {"$numberLong": "\1"}}', result
        )

        # Timestamp(seconds, increment) -> {"$timestamp": {"t": ..., "i": ...}}
        result = re.sub(
            r"Timestamp\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)",
            r'{"$timestamp": {"t": \1, "i": \2}}',
            result,
        )

        # NumberLong(...) -> {"$numberLong": "..."}
        result = re.sub(
            r'NumberLong\s*\(\s*["\']?(-?\d+)["\']?\s*\)',
            r'{"$numberLong": "\1"}',
            result,
        )

        # NumberInt(...) -> {"$numberInt": "..."}
        result = re.sub(
            r'NumberInt\s*\(\s*["\']?(-?\d+)["\']?\s*\)',
            r'{"$numberInt": "\1"}',
            result,
        )

        # NumberDecimal("...") -> {"$numberDecimal": "..."}
        result = re.sub(
            r'NumberDecimal\s*\(\s*["\']([^"\']+)["\']\s*\)',
            r'{"$numberDecimal": "\1"}',
            result,
        )

        # UUID("...") -> {"$uuid": "..."}
        result = re.sub(
            r'UUID\s*\(\s*["\']([^"\']+)["\']\s*\)', r'{"$uuid": "\1"}', result
        )

        # BinData(subtype, "base64") -> {"$binary": {"base64": "...", "subType": "..."}}
        result = re.sub(
            r'BinData\s*\(\s*(\d+)\s*,\s*["\']([^"\']+)["\']\s*\)',
            r'{"$binary": {"base64": "\2", "subType": "\1"}}',
            result,
        )

        # MinKey() -> {"$minKey": 1}
        result = re.sub(r"MinKey\s*\(\s*\)", r'{"$minKey": 1}', result)

        # MaxKey() -> {"$maxKey": 1}
        result = re.sub(r"MaxKey\s*\(\s*\)", r'{"$maxKey": 1}', result)

        # Code("javascript") -> {"$code": "..."}
        result = re.sub(
            r'Code\s*\(\s*["\']([^"\']+)["\']\s*\)', r'{"$code": "\1"}', result
        )

        # DBRef("collection", ObjectId("...")) - complex, handle after ObjectId conversion
        # First convert DBRef with already-converted ObjectId
        result = re.sub(
            r'DBRef\s*\(\s*["\'](\w+)["\']\s*,\s*(\{"\$oid":\s*"[^"]+"\})\s*\)',
            r'{"$ref": "\1", "$id": \2}',
            result,
        )

        # RegExp("pattern", "flags") -> {"$regularExpression": {"pattern": "...", "options": "..."}}
        result = re.sub(
            r'(?:new\s+)?RegExp\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
            r'{"$regularExpression": {"pattern": "\1", "options": "\2"}}',
            result,
        )
        # RegExp("pattern") without flags
        result = re.sub(
            r'(?:new\s+)?RegExp\s*\(\s*["\']([^"\']+)["\']\s*\)',
            r'{"$regularExpression": {"pattern": "\1", "options": ""}}',
            result,
        )

        # Regex literal /pattern/flags -> {"$regularExpression": {"pattern": "...", "options": "..."}}
        # This is tricky because / can appear in division. We look for it in value position.
        # Match: after : or [ or , with optional whitespace, /pattern/flags
        def replace_regex(match):
            prefix = match.group(1)
            pattern = match.group(2)
            flags = match.group(3) or ""
            # Escape backslashes and quotes in pattern for JSON
            escaped_pattern = pattern.replace("\\", "\\\\").replace('"', '\\"')
            return f'{prefix}{{"$regularExpression": {{"pattern": "{escaped_pattern}", "options": "{flags}"}}}}'

        result = re.sub(r"([:,\[]\s*)/([^/]+)/([gimsuvy]*)", replace_regex, result)

        # Handle JavaScript undefined -> null (MongoDB doesn't really use undefined in queries)
        result = re.sub(r"\bundefined\b", "null", result)

        # ===== Handle JavaScript syntax normalization =====

        # Replace single quotes with double quotes (but not inside already-quoted strings)
        # Simple approach: replace all single quotes
        result = result.replace("'", '"')

        # Quote unquoted keys: {key: value} -> {"key": value}
        # Match: after { or , (with optional whitespace), an unquoted identifier, then :
        result = re.sub(r"([{,])(\s*)([a-zA-Z_]\w*)(\s*:)", r'\1\2"\3"\4', result)

        # Quote MongoDB operators: {$match: ...} -> {"$match": ...}
        result = re.sub(r"([{,])(\s*)(\$\w+)(\s*:)", r'\1\2"\3"\4', result)

        # Fix any accidental double-quoting: ""key"" -> "key"
        result = re.sub(r'""(\w+)""', r'"\1"', result)
        result = re.sub(r'""\$(\w+)""', r'"$\1"', result)

        return result

    # NOTE: Extended JSON to BSON conversion is now handled by bson.json_util.loads()
    # in the _parse_extended_json method, which supports all BSON types including:
    # ObjectId, Date, Timestamp, NumberLong, NumberInt, NumberDecimal, UUID, Binary,
    # Regex, MinKey, MaxKey, Code, DBRef, etc.

    def _serialize_value(self, value: Any) -> Any:
        """
        Serialize a single BSON value to JSON-compatible format.

        Handles all BSON types:
        - ObjectId -> string
        - datetime -> ISO string
        - Timestamp -> {"t": seconds, "i": increment}
        - Decimal128 -> string
        - Binary -> base64 string
        - Regex -> {"pattern": "...", "options": "..."}
        - MinKey/MaxKey -> {"$minKey": 1} / {"$maxKey": 1}
        - Code -> string
        - DBRef -> {"$ref": "...", "$id": "..."}
        - UUID -> string
        """
        import base64

        if value is None:
            return None

        # Check for None-like types first
        value_type = type(value).__name__

        # ObjectId
        if value_type == "ObjectId":
            return str(value)

        # datetime
        if hasattr(value, "isoformat"):
            return value.isoformat()

        # Timestamp (BSON)
        if value_type == "Timestamp":
            return {"t": value.time, "i": value.inc}

        # Decimal128
        if value_type == "Decimal128":
            return str(value)

        # Binary
        if value_type == "Binary" or isinstance(value, (bytes, bytearray)):
            if isinstance(value, (bytes, bytearray)):
                return base64.b64encode(value).decode("utf-8")
            return base64.b64encode(bytes(value)).decode("utf-8")

        # Regex
        if value_type == "Regex":
            return {"pattern": value.pattern, "options": value.flags}

        # MinKey
        if value_type == "MinKey":
            return {"$minKey": 1}

        # MaxKey
        if value_type == "MaxKey":
            return {"$maxKey": 1}

        # Code
        if value_type == "Code":
            return str(value)

        # DBRef
        if value_type == "DBRef":
            result = {"$ref": value.collection, "$id": self._serialize_value(value.id)}
            if value.database:
                result["$db"] = value.database
            return result

        # UUID
        if value_type == "UUID":
            return str(value)

        # Int64 (bson.int64.Int64)
        if value_type == "Int64":
            return int(value)

        # Nested dict
        if isinstance(value, dict):
            return self._serialize_mongodb_doc(value)

        # List
        if isinstance(value, list):
            return [self._serialize_value(item) for item in value]

        # Standard JSON types pass through
        if isinstance(value, (str, int, float, bool)):
            return value

        # Fallback: convert to string
        return str(value)

    def _serialize_mongodb_doc(self, doc: Dict) -> Dict:
        """Convert MongoDB document to JSON-serializable format."""
        result = {}
        for key, value in doc.items():
            result[key] = self._serialize_value(value)
        return result

    async def execute(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute MongoDB query using pooled connections.

        Uses ConnectionPoolManager for efficient connection reuse
        across multiple sessions and tenants.
        """
        try:
            # Parse the query (already converts to BSON types via json_util.loads)
            collection_name, operation, query_args = self._parse_mongodb_query(query)

            # Extract database name from URL
            from urllib.parse import urlparse

            parsed = urlparse(connection_url)
            db_name = parsed.path.lstrip("/").split("?")[0]

            if not db_name:
                return self.error_result(
                    "Database name not specified in connection URL"
                )

            # Create DatabaseConfig for pool manager
            config = DatabaseConfig(db_type="mongodb", connection_url=connection_url)

            # Use shared connection pool manager
            async with pool_manager.get_connection(config) as client:
                db = client[db_name]
                collection = db[collection_name]

                fetch_limit = limit + 1  # Fetch one extra to detect has_more
                results: List[Dict] = []

                if operation == "find":
                    # Handle new format with filter and projection
                    if isinstance(query_args, dict) and "filter" in query_args:
                        filter_doc = query_args.get("filter", {})
                        projection = query_args.get("projection")
                        cursor = collection.find(filter_doc, projection).limit(
                            fetch_limit
                        )
                    else:
                        # Backwards compatibility - plain filter dict
                        cursor = collection.find(query_args).limit(fetch_limit)
                    async for doc in cursor:
                        results.append(self._serialize_mongodb_doc(doc))

                elif operation == "findone":
                    # Handle new format with filter and projection
                    if isinstance(query_args, dict) and "filter" in query_args:
                        filter_doc = query_args.get("filter", {})
                        projection = query_args.get("projection")
                        doc = await collection.find_one(filter_doc, projection)
                    else:
                        doc = await collection.find_one(query_args)
                    if doc:
                        results.append(self._serialize_mongodb_doc(doc))

                elif operation == "aggregate":
                    # Ensure query_args is a list (pipeline)
                    if not isinstance(query_args, list):
                        query_args = [query_args]

                    # Add $limit stage if not present
                    has_limit = any(
                        "$limit" in stage
                        for stage in query_args
                        if isinstance(stage, dict)
                    )
                    if not has_limit:
                        query_args.append({"$limit": fetch_limit})

                    cursor = collection.aggregate(query_args)
                    async for doc in cursor:
                        results.append(self._serialize_mongodb_doc(doc))

                return self.format_dict_results(results, limit)

        except ValueError as e:
            return self.error_result(str(e))
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"MongoDB query error ({error_type}): {e}")
            return self.error_result(f"Query execution failed: {str(e)}")

    async def test_connection(self, connection_url: str) -> Dict[str, Any]:
        """Test MongoDB connection using pool manager."""
        try:
            config = DatabaseConfig(db_type="mongodb", connection_url=connection_url)

            async with pool_manager.get_connection(config) as client:
                # Ping the server
                await client.admin.command("ping")

                # Get server info
                server_info = await client.server_info()
                version = server_info.get("version", "Unknown")

                return {
                    "success": True,
                    "message": "Connection successful",
                    "version": f"MongoDB {version}",
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "version": None,
            }

    def add_limit_to_query(self, query: str, limit: int) -> str:
        """MongoDB doesn't use SQL-style LIMIT - handled in execute()."""
        return query

    def _parse_mongodb_dml(self, query: str) -> Tuple[str, str, Any]:
        """
        Parse MongoDB DML (mutation) syntax.

        Supports:
        - db.collection.insertOne({document})
        - db.collection.updateOne({filter}, {update})
        - db.collection.deleteOne({filter})
        - db.collection.insertMany([{doc1}, {doc2}])
        - db.collection.updateMany({filter}, {update})
        - db.collection.deleteMany({filter})

        Returns:
            Tuple of (collection_name, operation, args)
        """
        query = query.strip().rstrip(";")

        # Match DML operations
        dml_pattern = r"db\.(\w+)\.(insertOne|updateOne|deleteOne|insertMany|updateMany|deleteMany)\s*\("
        match = re.match(dml_pattern, query, re.IGNORECASE)

        if not match:
            raise ValueError(
                "Invalid MongoDB DML. Use format: db.collection.insertOne({...}), "
                "db.collection.updateOne({filter}, {update}), or db.collection.deleteOne({filter})"
            )

        collection_name = match.group(1)
        operation = match.group(2).lower()

        # Extract arguments
        args_start = match.end()
        args_str = self._extract_balanced_args(query[args_start:])

        try:
            if operation in ("insertone", "insertmany"):
                # Single argument: document or array of documents
                normalized = self._normalize_json(args_str)
                args = self._parse_extended_json(normalized)
            else:
                # Two arguments: filter and update/options
                parts = self._split_args(args_str)
                if len(parts) < 1:
                    raise ValueError(f"{operation} requires at least a filter argument")

                filter_doc = self._parse_extended_json(self._normalize_json(parts[0]))

                if operation in ("updateone", "updatemany"):
                    if len(parts) < 2:
                        raise ValueError(
                            f"{operation} requires filter and update arguments"
                        )
                    update_doc = self._parse_extended_json(
                        self._normalize_json(parts[1])
                    )
                    args = {"filter": filter_doc, "update": update_doc}
                else:
                    # deleteOne/deleteMany - just filter
                    args = {"filter": filter_doc}

        except (json.JSONDecodeError, Exception) as e:
            raise ValueError(f"Invalid DML arguments: {e}")

        return collection_name, operation, args

    async def execute_dml(
        self, connection_url: str, sql: str, rollback: bool = True, timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute MongoDB DML (mutation) operations with transaction support.

        Args:
            connection_url: MongoDB connection URL
            sql: MongoDB DML statement (insertOne, updateOne, deleteOne, etc.)
            rollback: If True, rollback after execution (sandbox mode)
            timeout: Query timeout in seconds

        Returns:
            Dict with rows_affected, execution_time, error
        """
        from datetime import datetime

        from motor.motor_asyncio import AsyncIOMotorClient
        from pymongo.results import (
            DeleteResult,
            InsertManyResult,
            InsertOneResult,
            UpdateResult,
        )

        start_time = datetime.now()

        try:
            # Parse the DML operation (already converts to BSON types via json_util.loads)
            collection_name, operation, args = self._parse_mongodb_dml(sql)

            # Extract database name from URL
            from urllib.parse import urlparse

            parsed = urlparse(connection_url)
            db_name = parsed.path.lstrip("/").split("?")[0]

            if not db_name:
                return {
                    "success": False,
                    "rows_affected": 0,
                    "execution_time": (datetime.now() - start_time).total_seconds(),
                    "error": "Database name not specified in connection URL",
                }

            # Create direct client for transaction control
            client: AsyncIOMotorClient = AsyncIOMotorClient(connection_url)

            try:
                db = client[db_name]
                collection = db[collection_name]
                rows_affected: int = 0

                # Start session for transaction
                async with await client.start_session() as session:
                    async with session.start_transaction():
                        # Execute the DML operation
                        result: Union[
                            InsertOneResult, InsertManyResult, UpdateResult, DeleteResult
                        ]
                        if operation == "insertone":
                            result = await collection.insert_one(args, session=session)
                            rows_affected = 1 if result.inserted_id else 0

                        elif operation == "insertmany":
                            docs = args if isinstance(args, list) else [args]
                            result = await collection.insert_many(docs, session=session)
                            rows_affected = len(result.inserted_ids)

                        elif operation == "updateone":
                            result = await collection.update_one(
                                args["filter"], args["update"], session=session
                            )
                            rows_affected = result.modified_count

                        elif operation == "updatemany":
                            result = await collection.update_many(
                                args["filter"], args["update"], session=session
                            )
                            rows_affected = result.modified_count

                        elif operation == "deleteone":
                            result = await collection.delete_one(
                                args["filter"], session=session
                            )
                            rows_affected = result.deleted_count

                        elif operation == "deletemany":
                            result = await collection.delete_many(
                                args["filter"], session=session
                            )
                            rows_affected = result.deleted_count

                        # Rollback or commit
                        if rollback:
                            await session.abort_transaction()
                            logger.info(
                                f"MongoDB DML sandbox: {operation} {rows_affected} docs (rolled back)"
                            )
                        else:
                            await session.commit_transaction()
                            logger.info(
                                f"MongoDB DML executed: {operation} {rows_affected} docs"
                            )

                execution_time = (datetime.now() - start_time).total_seconds()

                return {
                    "success": True,
                    "rows_affected": rows_affected,
                    "execution_time": execution_time,
                    "error": None,
                }

            finally:
                client.close()  # Motor client close is sync but schedules cleanup

        except ValueError as e:
            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": str(e),
            }
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"MongoDB DML error ({error_type}): {e}")

            # Check for transaction not supported errors
            if "Transaction" in str(e) or "transaction" in str(e):
                error_msg = (
                    f"DML failed: {str(e)}. Note: MongoDB transactions require "
                    "a replica set or sharded cluster (MongoDB 4.0+). "
                    "Standalone servers don't support transactions."
                )
            else:
                error_msg = f"DML execution failed: {str(e)}"

            return {
                "success": False,
                "rows_affected": 0,
                "execution_time": (datetime.now() - start_time).total_seconds(),
                "error": error_msg,
            }
