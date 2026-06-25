"""
DynamoDB Logistics Benchmark Dataset

Hand-crafted NL-to-PartiQL benchmark cases targeting the logistics
tables in DynamoDB Local. Covers DynamoDB-specific patterns:

- Primary key lookups (HASH, HASH+RANGE)
- GSI queries
- Nested attribute access (maps, lists)
- PartiQL syntax for DynamoDB

Requires the logistics tables from ``data/dynamodb-init/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from benchmarks.core.dataset import BenchmarkDataset
from benchmarks.core.types import BenchmarkCase, DatabaseCategory, Difficulty

logger = logging.getLogger(__name__)

# Schema context describing DynamoDB tables and their key structures
_SCHEMA = """
-- DynamoDB tables (PartiQL syntax)

Table: warehouses
  Primary Key: warehouse_id (String) HASH
  Attributes: name, type, address, city, state, zip_code, country,
    latitude (Number), longitude (Number), capacity_sqft (Number),
    current_utilization_pct (Number), manager_name, phone,
    operating_hours, dock_doors (Number), is_active (Boolean),
    services (String Set)

Table: shipments
  Primary Key: shipment_id (String) HASH
  GSI warehouse-date-index: origin_warehouse_id (HASH), shipment_date (RANGE)
  GSI status-index: status (HASH)
  Attributes: origin_warehouse_id, destination_warehouse_id, shipment_date,
    expected_delivery_date, actual_delivery_date, status, priority,
    service_type, total_weight_lbs (Number), total_pieces (Number),
    total_pallets (Number), declared_value (Number), freight_class,
    customer_id, customer_name, customer_po, driver_id, vehicle_id,
    route_id, special_instructions, requires_signature (Boolean),
    is_hazmat (Boolean)

Table: tracking_events
  Primary Key: shipment_id (String) HASH, event_timestamp (String) RANGE
  Attributes: event_type, location, facility, description, updated_by

Table: fleet
  Primary Key: vehicle_id (String) HASH
  GSI warehouse-index: warehouse_id (HASH)
  Attributes: warehouse_id, vehicle_type, make, model, year (Number),
    vin, license_plate, capacity_lbs (Number), capacity_cubic_ft (Number),
    fuel_type, mpg (Number), current_mileage (Number), status,
    last_maintenance_date, next_maintenance_due, gps_enabled (Boolean),
    eld_device_id

Table: routes
  Primary Key: route_id (String) HASH
  GSI origin-index: origin_warehouse_id (HASH)
  Attributes: route_name, origin_warehouse_id, destination_warehouse_id,
    distance_miles (Number), estimated_duration_hours (Number),
    route_type, frequency, departure_time,
    stops (List of Maps with city, state, stop_type),
    toll_cost_estimate (Number), fuel_cost_estimate (Number),
    is_active (Boolean)

Table: drivers
  Primary Key: driver_id (String) HASH
  GSI warehouse-index: warehouse_id (HASH)
  Attributes: warehouse_id, first_name, last_name, email, phone,
    license_number, license_class, license_expiry, hire_date, status,
    total_deliveries (Number), on_time_rate_pct (Number),
    safety_score (Number), certifications (String Set)
"""

# NL-to-PartiQL benchmark cases
_CASES: List[dict] = [
    # --- SIMPLE: Direct primary-key lookups ---
    {
        "id": "ddb_001",
        "nl": "Get the details of warehouse WH001.",
        "partiql": "SELECT * FROM warehouses WHERE warehouse_id = 'WH001'",
        "difficulty": "simple",
    },
    {
        "id": "ddb_002",
        "nl": "Show all warehouses.",
        "partiql": "SELECT * FROM warehouses",
        "difficulty": "simple",
    },
    {
        "id": "ddb_003",
        "nl": "Get information about shipment SHP-2025-00001.",
        "partiql": "SELECT * FROM shipments WHERE shipment_id = 'SHP-2025-00001'",
        "difficulty": "simple",
    },
    {
        "id": "ddb_004",
        "nl": "List all drivers.",
        "partiql": "SELECT * FROM drivers",
        "difficulty": "simple",
    },
    {
        "id": "ddb_005",
        "nl": "Get the details of driver DRV003.",
        "partiql": "SELECT * FROM drivers WHERE driver_id = 'DRV003'",
        "difficulty": "simple",
    },
    {
        "id": "ddb_006",
        "nl": "Show all vehicles in the fleet.",
        "partiql": "SELECT * FROM fleet",
        "difficulty": "simple",
    },
    {
        "id": "ddb_007",
        "nl": "Get information about vehicle VEH004.",
        "partiql": "SELECT * FROM fleet WHERE vehicle_id = 'VEH004'",
        "difficulty": "simple",
    },
    {
        "id": "ddb_008",
        "nl": "Show all routes.",
        "partiql": "SELECT * FROM routes",
        "difficulty": "simple",
    },
    # --- MODERATE: Specific columns, composite keys, basic filtering ---
    {
        "id": "ddb_009",
        "nl": "What are the names and cities of all warehouses?",
        "partiql": "SELECT name, city FROM warehouses",
        "difficulty": "moderate",
    },
    {
        "id": "ddb_010",
        "nl": "Show the name, license class, and total deliveries for all drivers.",
        "partiql": "SELECT first_name, last_name, license_class, total_deliveries FROM drivers",
        "difficulty": "moderate",
    },
    {
        "id": "ddb_011",
        "nl": "Get all tracking events for shipment SHP-2025-00004.",
        "partiql": "SELECT * FROM tracking_events WHERE shipment_id = 'SHP-2025-00004'",
        "difficulty": "moderate",
    },
    {
        "id": "ddb_012",
        "nl": "Show the route name, distance, and estimated duration for route RT002.",
        "partiql": "SELECT route_name, distance_miles, estimated_duration_hours FROM routes WHERE route_id = 'RT002'",
        "difficulty": "moderate",
    },
    {
        "id": "ddb_013",
        "nl": "List the vehicle type, make, model, and capacity for all fleet vehicles.",
        "partiql": "SELECT vehicle_type, make, model, capacity_lbs FROM fleet",
        "difficulty": "moderate",
    },
    {
        "id": "ddb_014",
        "nl": "Show shipment details including customer name and declared value for shipment SHP-2025-00002.",
        "partiql": "SELECT customer_name, declared_value, priority, service_type FROM shipments WHERE shipment_id = 'SHP-2025-00002'",
        "difficulty": "moderate",
    },
    {
        "id": "ddb_015",
        "nl": "Get the name and capacity of warehouse WH003.",
        "partiql": "SELECT name, capacity_sqft FROM warehouses WHERE warehouse_id = 'WH003'",
        "difficulty": "moderate",
    },
    {
        "id": "ddb_016",
        "nl": "Show all tracking events for shipment SHP-2025-00001 after January 8 2025 at noon.",
        "partiql": "SELECT * FROM tracking_events WHERE shipment_id = 'SHP-2025-00001' AND event_timestamp > '2025-01-08T12:00:00Z'",
        "difficulty": "moderate",
        "evidence": "tracking_events has a composite key: shipment_id (HASH) + event_timestamp (RANGE). Range key queries use comparison operators.",
    },
    # --- CHALLENGING: GSI queries, nested access, complex conditions ---
    {
        "id": "ddb_017",
        "nl": "Find all shipments originating from warehouse WH003.",
        "partiql": "SELECT * FROM shipments.\"warehouse-date-index\" WHERE origin_warehouse_id = 'WH003'",
        "difficulty": "challenging",
        "evidence": "Use the GSI 'warehouse-date-index' with origin_warehouse_id as partition key. PartiQL accesses GSIs via tablename.\"index-name\" syntax.",
    },
    {
        "id": "ddb_018",
        "nl": "Find all shipments with status 'In Transit'.",
        "partiql": "SELECT * FROM shipments.\"status-index\" WHERE status = 'In Transit'",
        "difficulty": "challenging",
        "evidence": "Use the GSI 'status-index' with status as partition key.",
    },
    {
        "id": "ddb_019",
        "nl": "List all vehicles assigned to warehouse WH003.",
        "partiql": "SELECT * FROM fleet.\"warehouse-index\" WHERE warehouse_id = 'WH003'",
        "difficulty": "challenging",
        "evidence": "Use the GSI 'warehouse-index' on fleet table with warehouse_id as partition key.",
    },
    {
        "id": "ddb_020",
        "nl": "Find all drivers assigned to warehouse WH001.",
        "partiql": "SELECT * FROM drivers.\"warehouse-index\" WHERE warehouse_id = 'WH001'",
        "difficulty": "challenging",
        "evidence": "Use the GSI 'warehouse-index' on drivers table.",
    },
    {
        "id": "ddb_021",
        "nl": "List all routes originating from warehouse WH005.",
        "partiql": "SELECT * FROM routes.\"origin-index\" WHERE origin_warehouse_id = 'WH005'",
        "difficulty": "challenging",
        "evidence": "Use the GSI 'origin-index' on routes table.",
    },
    {
        "id": "ddb_022",
        "nl": "Find shipments from warehouse WH001 shipped on January 8, 2025.",
        "partiql": "SELECT * FROM shipments.\"warehouse-date-index\" WHERE origin_warehouse_id = 'WH001' AND shipment_date = '2025-01-08'",
        "difficulty": "challenging",
        "evidence": "GSI 'warehouse-date-index' supports both partition (origin_warehouse_id) and sort key (shipment_date) queries.",
    },
    {
        "id": "ddb_023",
        "nl": "What is the on-time delivery rate and safety score for each driver?",
        "partiql": "SELECT first_name, last_name, on_time_rate_pct, safety_score FROM drivers",
        "difficulty": "challenging",
    },
    {
        "id": "ddb_024",
        "nl": "Show the stops for route RT001.",
        "partiql": "SELECT route_name, stops FROM routes WHERE route_id = 'RT001'",
        "difficulty": "challenging",
        "evidence": "The 'stops' attribute is a List of Maps. PartiQL returns it as a nested structure.",
    },
    {
        "id": "ddb_025",
        "nl": "Show the toll and fuel cost estimates for all routes.",
        "partiql": "SELECT route_name, toll_cost_estimate, fuel_cost_estimate FROM routes",
        "difficulty": "challenging",
    },
]


class DynamoDBLogisticsDataset(BenchmarkDataset):
    """Hand-crafted NL-to-PartiQL benchmark for the logistics tables."""

    NAME = "dynamodb-logistics"
    DESCRIPTION = "25 NL-to-PartiQL questions on a logistics schema (DynamoDB)"
    DB_TYPE = DatabaseCategory.NOSQL_KEY_VALUE
    SOURCE_URL = ""  # bundled in-repo
    TOTAL_CASES = 25

    def load(self, data_dir: Path) -> List[BenchmarkCase]:
        """Load the hand-crafted PartiQL benchmark cases."""
        cases = []
        for item in _CASES:
            difficulty_map = {
                "simple": Difficulty.SIMPLE,
                "moderate": Difficulty.MODERATE,
                "challenging": Difficulty.CHALLENGING,
            }
            cases.append(
                BenchmarkCase(
                    case_id=item["id"],
                    natural_language=item["nl"],
                    gold_query=item["partiql"],
                    db_name="logistics",
                    db_type=DatabaseCategory.NOSQL_KEY_VALUE,
                    difficulty=difficulty_map.get(item["difficulty"], Difficulty.SIMPLE),
                    evidence=item.get("evidence"),
                    schema_context=_SCHEMA,
                )
            )
        logger.info("Loaded %d DynamoDB logistics benchmark cases", len(cases))
        return cases

    def download(self, data_dir: Path) -> None:
        """No download needed — cases are bundled in this module."""
        logger.info("DynamoDB logistics dataset is bundled (no download required)")
