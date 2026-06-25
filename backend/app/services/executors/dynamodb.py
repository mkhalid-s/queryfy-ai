"""
QueryfyAI - DynamoDB Query Executor

DynamoDB executor using PartiQL for SQL-like query execution.
Uses aioboto3 for async operations.
"""

import asyncio
import base64
import logging
import re
from typing import Any, Dict, Optional

from .base import QueryExecutor

logger = logging.getLogger(__name__)


class DynamoDBExecutor(QueryExecutor):
    """
    DynamoDB query executor using PartiQL.

    Features:
    - PartiQL SELECT query execution
    - Type serialization for DynamoDB types
    - Pagination handling
    - Local DynamoDB support
    """

    DB_TYPE = "dynamodb"
    SUPPORTS_ASYNC = True

    def _parse_connection_url(self, url: str) -> Dict[str, Any]:
        """Parse DynamoDB connection URL."""
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

    def _sanitize_query(self, query: str) -> str:
        """
        Sanitize PartiQL query for safe execution.

        Only allows SELECT statements.
        """
        query = query.strip()

        # Remove trailing semicolons
        query = query.rstrip(";")

        # Ensure it's a SELECT query
        if not query.upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")

        # Block dangerous keywords
        dangerous_patterns = [
            r"\bDELETE\b",
            r"\bINSERT\b",
            r"\bUPDATE\b",
            r"\bCREATE\b",
            r"\bDROP\b",
            r"\bALTER\b",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                raise ValueError("Query contains forbidden operation")

        return query

    def _deserialize_dynamodb_value(self, value: Dict[str, Any]) -> Any:
        """
        Convert DynamoDB typed value to Python native type.

        DynamoDB returns values as {"S": "string"}, {"N": "123"}, etc.
        """
        if value is None:
            return None

        if not isinstance(value, dict):
            return value

        for type_code, val in value.items():
            if type_code == "S":
                return val
            elif type_code == "N":
                # Return as float if it has decimal point, else int
                return float(val) if "." in val else int(val)
            elif type_code == "B":
                # Binary - return as base64 string
                return (
                    base64.b64encode(val).decode("utf-8")
                    if isinstance(val, bytes)
                    else val
                )
            elif type_code == "BOOL":
                return val
            elif type_code == "NULL":
                return None
            elif type_code == "SS":
                return list(val)
            elif type_code == "NS":
                return [float(v) if "." in v else int(v) for v in val]
            elif type_code == "BS":
                return [
                    base64.b64encode(v).decode("utf-8") if isinstance(v, bytes) else v
                    for v in val
                ]
            elif type_code == "L":
                return [self._deserialize_dynamodb_value(item) for item in val]
            elif type_code == "M":
                return {k: self._deserialize_dynamodb_value(v) for k, v in val.items()}

        # Unknown type - return as-is
        return value

    def _deserialize_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Deserialize a DynamoDB item to a Python dict."""
        return {
            key: self._deserialize_dynamodb_value(value) for key, value in item.items()
        }

    async def execute(
        self,
        connection_url: str,
        query: str,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute PartiQL query against DynamoDB.
        """
        import aioboto3

        try:
            # Sanitize query
            query = self._sanitize_query(query)

            # Parse connection URL
            params = self._parse_connection_url(connection_url)

            # Build client kwargs
            client_kwargs = {}
            if params["region"] and params["region"] != "local":
                client_kwargs["region_name"] = params["region"]
            if params["endpoint_url"]:
                client_kwargs["endpoint_url"] = params["endpoint_url"]
            if params["access_key"] and params["secret_key"]:
                client_kwargs["aws_access_key_id"] = params["access_key"]
                client_kwargs["aws_secret_access_key"] = params["secret_key"]

            session = aioboto3.Session()

            async with session.client("dynamodb", **client_kwargs) as client:
                # Execute PartiQL query
                all_items = []
                next_token = None
                fetch_limit = limit + 1  # Fetch one extra to detect has_more

                while True:
                    # Build request
                    request_params = {
                        "Statement": query,
                    }

                    if next_token:
                        request_params["NextToken"] = next_token

                    # Execute with optional timeout
                    if timeout:
                        response = await asyncio.wait_for(
                            client.execute_statement(**request_params), timeout=timeout
                        )
                    else:
                        response = await client.execute_statement(**request_params)

                    # Collect items
                    items = response.get("Items", [])
                    all_items.extend(items)

                    # Check if we have enough items
                    if len(all_items) >= fetch_limit:
                        break

                    # Check for more pages
                    next_token = response.get("NextToken")
                    if not next_token:
                        break

                if not all_items:
                    return {
                        "success": True,
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "has_more": False,
                        "error": None,
                    }

                # Deserialize items
                deserialized = [self._deserialize_item(item) for item in all_items]

                # Determine has_more
                has_more = len(deserialized) > limit
                result_rows = deserialized[:limit] if has_more else deserialized

                # Extract columns from first row
                columns = list(result_rows[0].keys()) if result_rows else []

                return {
                    "success": True,
                    "columns": columns,
                    "rows": result_rows,
                    "row_count": len(result_rows),
                    "has_more": has_more,
                    "error": None,
                }

        except ValueError as e:
            # Query validation errors
            return self.error_result(str(e))
        except asyncio.TimeoutError:
            logger.warning(f"DynamoDB query timeout after {timeout}s")
            return self.error_result(f"Query exceeded timeout of {timeout} seconds")
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            # Parse AWS error messages for better UX
            if "ValidationException" in error_msg:
                error_msg = f"PartiQL syntax error: {error_msg}"
            elif "ResourceNotFoundException" in error_msg:
                error_msg = "Table not found"
            elif "AccessDeniedException" in error_msg:
                error_msg = "Access denied - check your AWS credentials"

            logger.error(f"DynamoDB query error ({error_type}): {e}")
            return self.error_result(f"Query execution failed: {error_msg}")

    async def test_connection(self, connection_url: str) -> Dict[str, Any]:
        """Test DynamoDB connection."""
        import aioboto3

        try:
            params = self._parse_connection_url(connection_url)

            client_kwargs = {}
            if params["region"] and params["region"] != "local":
                client_kwargs["region_name"] = params["region"]
            if params["endpoint_url"]:
                client_kwargs["endpoint_url"] = params["endpoint_url"]
            if params["access_key"] and params["secret_key"]:
                client_kwargs["aws_access_key_id"] = params["access_key"]
                client_kwargs["aws_secret_access_key"] = params["secret_key"]

            session = aioboto3.Session()

            async with session.client("dynamodb", **client_kwargs) as client:
                # List tables to verify connection
                response = await client.list_tables(Limit=1)
                table_count = len(response.get("TableNames", []))

                endpoint = params["endpoint_url"] or f"DynamoDB ({params['region']})"
                return {
                    "success": True,
                    "message": f"Connection successful to {endpoint}",
                    "version": f"DynamoDB (tables found: {table_count}+)",
                }

        except Exception as e:
            error_msg = str(e)
            if "UnrecognizedClientException" in error_msg:
                error_msg = "Invalid AWS credentials"
            elif "EndpointConnectionError" in error_msg:
                error_msg = "Could not connect to DynamoDB endpoint"

            return {
                "success": False,
                "message": f"Connection failed: {error_msg}",
                "version": None,
            }
