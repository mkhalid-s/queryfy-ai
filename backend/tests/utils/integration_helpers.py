"""
Integration Test Utilities

Utilities for testing backend ↔ frontend integration:
- Field transformation (snake_case ↔ camelCase)
- API contract validation
- SSE event format validation
- Response format compatibility
"""

import json
from typing import Any, Dict, List, Set


def to_camel_case(snake_str: str) -> str:
    """
    Convert snake_case to camelCase, preserving leading underscores

    Examples:
        user_id → userId
        created_at → createdAt
        total_count → totalCount
        _user_id → _userId (preserves leading underscore)
        API_KEY → apiKey (first component lowercase)
    """
    # Preserve leading underscores
    leading_underscores = ''
    while snake_str.startswith('_'):
        leading_underscores += '_'
        snake_str = snake_str[1:]

    if not snake_str:
        return leading_underscores

    components = snake_str.split('_')
    # First component is lowercase, rest are title case
    return leading_underscores + components[0].lower() + ''.join(x.title() for x in components[1:])


def to_snake_case(camel_str: str) -> str:
    """
    Convert camelCase to snake_case, handling acronyms correctly

    Examples:
        userId → user_id
        createdAt → created_at
        totalCount → total_count
        APIKey → api_key (not a_p_i_key)
        xmlHTTPRequest → xml_http_request
    """
    # Insert underscore before uppercase letters, but handle consecutive uppercase correctly
    result = []
    for i, char in enumerate(camel_str):
        if char.isupper():
            # Insert underscore if:
            # - Not first character AND
            # - Previous character was not uppercase (end of lowercase sequence)
            # OR
            # - Previous was uppercase but next is lowercase (end of acronym like "APIKey" → "API_Key")
            if i > 0:
                prev_is_upper = camel_str[i-1].isupper()
                next_is_lower = i < len(camel_str) - 1 and camel_str[i+1].islower()

                if not prev_is_upper or (prev_is_upper and next_is_lower):
                    result.append('_')

        result.append(char.lower())
    return ''.join(result)


def transform_keys_to_camel(obj: Any) -> Any:
    """
    Recursively transform all dictionary keys from snake_case to camelCase

    Used to simulate frontend transformation of backend responses
    """
    if isinstance(obj, dict):
        return {
            to_camel_case(k): transform_keys_to_camel(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [transform_keys_to_camel(item) for item in obj]
    else:
        return obj


def transform_keys_to_snake(obj: Any) -> Any:
    """
    Recursively transform all dictionary keys from camelCase to snake_case

    Used to simulate backend transformation of frontend requests
    """
    if isinstance(obj, dict):
        return {
            to_snake_case(k): transform_keys_to_snake(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [transform_keys_to_snake(item) for item in obj]
    else:
        return obj


def validate_sse_event(event_line: str) -> Dict[str, Any]:
    """
    Validate and parse SSE event format

    SSE format:
        data: {"type": "status", "content": "Thinking..."}

    Returns parsed event data or raises ValueError
    """
    if not event_line.startswith('data: '):
        raise ValueError(f"Invalid SSE format: must start with 'data: ', got: {event_line[:50]}")

    json_str = event_line[6:]  # Remove 'data: ' prefix

    try:
        event_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid SSE JSON: {e}, data: {json_str[:100]}")

    # Validate required fields
    if 'type' not in event_data:
        raise ValueError(f"SSE event missing 'type' field: {event_data}")

    return event_data


def validate_error_response(response: Dict[str, Any]) -> None:
    """
    Validate error response format

    Expected format:
        {
            "success": false,
            "error": "Error message",
            "error_type": "VALIDATION_ERROR",
            "details": {...}  // Optional
        }
    """
    if 'success' not in response:
        raise ValueError("Error response missing 'success' field")

    if response.get('success') is not False:
        raise ValueError(f"Error response should have success=false, got: {response.get('success')}")

    if 'error' not in response:
        raise ValueError("Error response missing 'error' field")

    if not isinstance(response['error'], str):
        raise ValueError(f"Error field should be string, got: {type(response['error'])}")


def validate_chart_spec(chart_spec: Dict[str, Any]) -> None:
    """
    Validate chart specification format

    Required fields: chart_type, x_axis, y_axis, data
    """
    required_fields = ['chart_type', 'x_axis', 'y_axis', 'data']

    for field in required_fields:
        if field not in chart_spec:
            raise ValueError(f"Chart spec missing required field: {field}")

    # Validate chart_type
    valid_types = ['bar', 'line', 'pie', 'scatter', 'area', 'column']
    if chart_spec['chart_type'] not in valid_types:
        raise ValueError(f"Invalid chart_type: {chart_spec['chart_type']}, must be one of {valid_types}")

    # Validate data is list
    if not isinstance(chart_spec['data'], list):
        raise ValueError(f"Chart data must be list, got: {type(chart_spec['data'])}")


def compare_schemas(backend_response: Dict[str, Any], frontend_expected: Dict[str, Any]) -> List[str]:
    """
    Compare backend response schema with frontend expectations

    Returns list of differences/mismatches
    """
    differences = []

    # Check for missing fields in backend response
    for key in frontend_expected.keys():
        snake_key = to_snake_case(key)
        if snake_key not in backend_response:
            differences.append(f"Frontend expects '{key}' (backend: '{snake_key}') but not found in response")

    # Check for extra fields in backend response
    for key in backend_response.keys():
        camel_key = to_camel_case(key)
        if camel_key not in frontend_expected:
            differences.append(f"Backend returns '{key}' (frontend: '{camel_key}') but not expected by frontend")

    return differences


def validate_timestamp_format(timestamp_str: str) -> None:
    """
    Validate ISO8601 timestamp format

    Expected format: 2024-01-15T10:30:00Z or 2024-01-15T10:30:00.123456Z
    """
    from datetime import datetime

    # Try parsing as ISO8601
    formats = [
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S.%f%z'
    ]

    parsed = False
    for fmt in formats:
        try:
            datetime.strptime(timestamp_str, fmt)
            parsed = True
            break
        except ValueError:
            continue

    if not parsed:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}, expected ISO8601")


def validate_sql_hash(sql_hash: str) -> None:
    """
    Validate SQL hash format

    Expected: 32-character hex string (MD5) or 64-character (SHA256)
    """
    if not isinstance(sql_hash, str):
        raise ValueError(f"SQL hash must be string, got: {type(sql_hash)}")

    if len(sql_hash) not in [32, 64]:
        raise ValueError(f"SQL hash must be 32 or 64 characters, got: {len(sql_hash)}")

    if not all(c in '0123456789abcdef' for c in sql_hash.lower()):
        raise ValueError(f"SQL hash must be hexadecimal, got: {sql_hash}")


def extract_required_fields(schema_dict: Dict[str, Any]) -> Set[str]:
    """
    Extract required fields from Pydantic schema

    Used for contract validation
    """
    required = set()

    if isinstance(schema_dict, dict):
        if 'required' in schema_dict:
            required.update(schema_dict['required'])

        # Recursively check properties
        if 'properties' in schema_dict:
            for prop_name, prop_schema in schema_dict['properties'].items():
                # Check if field has default value (not required)
                if 'default' not in prop_schema and prop_name in schema_dict.get('required', []):
                    required.add(prop_name)

    return required


def validate_field_types(data: Dict[str, Any], expected_types: Dict[str, type]) -> List[str]:
    """
    Validate field types match expectations

    Returns list of type mismatches
    """
    mismatches = []

    for field, expected_type in expected_types.items():
        if field in data:
            actual_type = type(data[field])

            # Handle None values
            if data[field] is None:
                continue

            # Check type match
            if not isinstance(data[field], expected_type):
                mismatches.append(
                    f"Field '{field}' expected type {expected_type.__name__}, "
                    f"got {actual_type.__name__}: {data[field]}"
                )

    return mismatches


def create_mock_sse_stream(events: List[Dict[str, Any]]) -> str:
    """
    Create mock SSE stream for testing

    Args:
        events: List of event dictionaries

    Returns:
        SSE formatted string
    """
    lines = []
    for event in events:
        lines.append(f"data: {json.dumps(event)}\n")
    return '\n'.join(lines)


def parse_sse_stream(sse_text: str) -> List[Dict[str, Any]]:
    """
    Parse SSE stream text into list of events

    Args:
        sse_text: Raw SSE stream text

    Returns:
        List of parsed event dictionaries
    """
    events = []
    lines = sse_text.strip().split('\n')

    for line in lines:
        line = line.strip()
        if line.startswith('data: '):
            try:
                event_data = validate_sse_event(line)
                events.append(event_data)
            except ValueError:
                # Skip invalid events
                continue

    return events
