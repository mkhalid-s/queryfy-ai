#!/bin/bash
# ============================================================================
# LOGISTICS DYNAMODB INITIALIZATION SCRIPT
# Comprehensive mock data for logistics/shipping domain
# ============================================================================

set -e

# Configuration
export AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-local}
export AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-local}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-east-1}
ENDPOINT="${DYNAMODB_ENDPOINT:-http://localhost:8000}"

echo "============================================"
echo "Initializing DynamoDB Logistics Database"
echo "============================================"

# Wait for DynamoDB to be ready
echo "Waiting for DynamoDB to be ready..."
until aws dynamodb list-tables --endpoint-url $ENDPOINT > /dev/null 2>&1; do
    sleep 2
done
echo "DynamoDB is ready!"

# ============================================================================
# CREATE TABLES
# ============================================================================

echo "Creating tables..."

# Warehouses Table
aws dynamodb create-table \
    --endpoint-url $ENDPOINT \
    --table-name warehouses \
    --attribute-definitions \
        AttributeName=warehouse_id,AttributeType=S \
    --key-schema \
        AttributeName=warehouse_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || echo "Table 'warehouses' already exists"

# Shipments Table (partition by origin_warehouse, sort by shipment_date)
aws dynamodb create-table \
    --endpoint-url $ENDPOINT \
    --table-name shipments \
    --attribute-definitions \
        AttributeName=shipment_id,AttributeType=S \
        AttributeName=origin_warehouse_id,AttributeType=S \
        AttributeName=shipment_date,AttributeType=S \
        AttributeName=status,AttributeType=S \
    --key-schema \
        AttributeName=shipment_id,KeyType=HASH \
    --global-secondary-indexes \
        "[{\"IndexName\":\"warehouse-date-index\",\"KeySchema\":[{\"AttributeName\":\"origin_warehouse_id\",\"KeyType\":\"HASH\"},{\"AttributeName\":\"shipment_date\",\"KeyType\":\"RANGE\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}},{\"IndexName\":\"status-index\",\"KeySchema\":[{\"AttributeName\":\"status\",\"KeyType\":\"HASH\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}]" \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || echo "Table 'shipments' already exists"

# Tracking Events Table (partition by shipment_id, sort by timestamp)
aws dynamodb create-table \
    --endpoint-url $ENDPOINT \
    --table-name tracking_events \
    --attribute-definitions \
        AttributeName=shipment_id,AttributeType=S \
        AttributeName=event_timestamp,AttributeType=S \
    --key-schema \
        AttributeName=shipment_id,KeyType=HASH \
        AttributeName=event_timestamp,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || echo "Table 'tracking_events' already exists"

# Vehicles/Fleet Table
aws dynamodb create-table \
    --endpoint-url $ENDPOINT \
    --table-name fleet \
    --attribute-definitions \
        AttributeName=vehicle_id,AttributeType=S \
        AttributeName=warehouse_id,AttributeType=S \
    --key-schema \
        AttributeName=vehicle_id,KeyType=HASH \
    --global-secondary-indexes \
        "[{\"IndexName\":\"warehouse-index\",\"KeySchema\":[{\"AttributeName\":\"warehouse_id\",\"KeyType\":\"HASH\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}]" \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || echo "Table 'fleet' already exists"

# Routes Table
aws dynamodb create-table \
    --endpoint-url $ENDPOINT \
    --table-name routes \
    --attribute-definitions \
        AttributeName=route_id,AttributeType=S \
        AttributeName=origin_warehouse_id,AttributeType=S \
    --key-schema \
        AttributeName=route_id,KeyType=HASH \
    --global-secondary-indexes \
        "[{\"IndexName\":\"origin-index\",\"KeySchema\":[{\"AttributeName\":\"origin_warehouse_id\",\"KeyType\":\"HASH\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}]" \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || echo "Table 'routes' already exists"

# Drivers Table
aws dynamodb create-table \
    --endpoint-url $ENDPOINT \
    --table-name drivers \
    --attribute-definitions \
        AttributeName=driver_id,AttributeType=S \
        AttributeName=warehouse_id,AttributeType=S \
    --key-schema \
        AttributeName=driver_id,KeyType=HASH \
    --global-secondary-indexes \
        "[{\"IndexName\":\"warehouse-index\",\"KeySchema\":[{\"AttributeName\":\"warehouse_id\",\"KeyType\":\"HASH\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}]" \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || echo "Table 'drivers' already exists"

# Wait for tables to be active
echo "Waiting for tables to become active..."
sleep 5

# ============================================================================
# INSERT WAREHOUSES
# ============================================================================
echo "Inserting warehouse data..."

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name warehouses --item '{
    "warehouse_id": {"S": "WH001"},
    "name": {"S": "Northeast Distribution Center"},
    "type": {"S": "Distribution Center"},
    "address": {"S": "100 Logistics Way"},
    "city": {"S": "Newark"},
    "state": {"S": "NJ"},
    "zip_code": {"S": "07102"},
    "country": {"S": "USA"},
    "latitude": {"N": "40.7357"},
    "longitude": {"N": "-74.1724"},
    "capacity_sqft": {"N": "500000"},
    "current_utilization_pct": {"N": "78"},
    "manager_name": {"S": "Robert Martinez"},
    "phone": {"S": "(973) 555-0100"},
    "operating_hours": {"S": "24/7"},
    "dock_doors": {"N": "45"},
    "is_active": {"BOOL": true},
    "services": {"SS": ["Cross-docking", "Cold Storage", "Hazmat", "Same-day Processing"]}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name warehouses --item '{
    "warehouse_id": {"S": "WH002"},
    "name": {"S": "Southeast Fulfillment Hub"},
    "type": {"S": "Fulfillment Center"},
    "address": {"S": "200 Commerce Parkway"},
    "city": {"S": "Atlanta"},
    "state": {"S": "GA"},
    "zip_code": {"S": "30301"},
    "country": {"S": "USA"},
    "latitude": {"N": "33.7490"},
    "longitude": {"N": "-84.3880"},
    "capacity_sqft": {"N": "750000"},
    "current_utilization_pct": {"N": "82"},
    "manager_name": {"S": "Angela Thompson"},
    "phone": {"S": "(404) 555-0200"},
    "operating_hours": {"S": "24/7"},
    "dock_doors": {"N": "60"},
    "is_active": {"BOOL": true},
    "services": {"SS": ["E-commerce Fulfillment", "Returns Processing", "Gift Wrapping", "Kitting"]}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name warehouses --item '{
    "warehouse_id": {"S": "WH003"},
    "name": {"S": "West Coast Mega Hub"},
    "type": {"S": "Distribution Center"},
    "address": {"S": "300 Port Boulevard"},
    "city": {"S": "Los Angeles"},
    "state": {"S": "CA"},
    "zip_code": {"S": "90731"},
    "country": {"S": "USA"},
    "latitude": {"N": "33.7395"},
    "longitude": {"N": "-118.2673"},
    "capacity_sqft": {"N": "1200000"},
    "current_utilization_pct": {"N": "91"},
    "manager_name": {"S": "David Chen"},
    "phone": {"S": "(310) 555-0300"},
    "operating_hours": {"S": "24/7"},
    "dock_doors": {"N": "85"},
    "is_active": {"BOOL": true},
    "services": {"SS": ["Import/Export", "Container Drayage", "Cross-docking", "Cold Storage"]}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name warehouses --item '{
    "warehouse_id": {"S": "WH004"},
    "name": {"S": "Midwest Regional Center"},
    "type": {"S": "Regional Hub"},
    "address": {"S": "400 Industrial Drive"},
    "city": {"S": "Chicago"},
    "state": {"S": "IL"},
    "zip_code": {"S": "60601"},
    "country": {"S": "USA"},
    "latitude": {"N": "41.8781"},
    "longitude": {"N": "-87.6298"},
    "capacity_sqft": {"N": "650000"},
    "current_utilization_pct": {"N": "74"},
    "manager_name": {"S": "Sarah Johnson"},
    "phone": {"S": "(312) 555-0400"},
    "operating_hours": {"S": "6AM-10PM"},
    "dock_doors": {"N": "52"},
    "is_active": {"BOOL": true},
    "services": {"SS": ["LTL Consolidation", "Cross-docking", "Inventory Management"]}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name warehouses --item '{
    "warehouse_id": {"S": "WH005"},
    "name": {"S": "Texas Distribution Campus"},
    "type": {"S": "Distribution Center"},
    "address": {"S": "500 Freight Lane"},
    "city": {"S": "Dallas"},
    "state": {"S": "TX"},
    "zip_code": {"S": "75201"},
    "country": {"S": "USA"},
    "latitude": {"N": "32.7767"},
    "longitude": {"N": "-96.7970"},
    "capacity_sqft": {"N": "900000"},
    "current_utilization_pct": {"N": "68"},
    "manager_name": {"S": "Michael Rodriguez"},
    "phone": {"S": "(214) 555-0500"},
    "operating_hours": {"S": "24/7"},
    "dock_doors": {"N": "70"},
    "is_active": {"BOOL": true},
    "services": {"SS": ["Cross-docking", "E-commerce Fulfillment", "Hazmat"]}
}'

# ============================================================================
# INSERT DRIVERS
# ============================================================================
echo "Inserting driver data..."

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name drivers --item '{
    "driver_id": {"S": "DRV001"},
    "warehouse_id": {"S": "WH001"},
    "first_name": {"S": "John"},
    "last_name": {"S": "Smith"},
    "email": {"S": "john.smith@logistics.com"},
    "phone": {"S": "(973) 555-1001"},
    "license_number": {"S": "NJ123456789"},
    "license_class": {"S": "CDL-A"},
    "license_expiry": {"S": "2026-08-15"},
    "hire_date": {"S": "2018-03-20"},
    "status": {"S": "Active"},
    "total_deliveries": {"N": "4521"},
    "on_time_rate_pct": {"N": "98.5"},
    "safety_score": {"N": "95"},
    "certifications": {"SS": ["Hazmat", "Tanker", "Doubles/Triples"]}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name drivers --item '{
    "driver_id": {"S": "DRV002"},
    "warehouse_id": {"S": "WH002"},
    "first_name": {"S": "Maria"},
    "last_name": {"S": "Garcia"},
    "email": {"S": "maria.garcia@logistics.com"},
    "phone": {"S": "(404) 555-2002"},
    "license_number": {"S": "GA987654321"},
    "license_class": {"S": "CDL-A"},
    "license_expiry": {"S": "2025-11-30"},
    "hire_date": {"S": "2019-07-15"},
    "status": {"S": "Active"},
    "total_deliveries": {"N": "3892"},
    "on_time_rate_pct": {"N": "99.1"},
    "safety_score": {"N": "98"},
    "certifications": {"SS": ["Hazmat", "Refrigerated"]}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name drivers --item '{
    "driver_id": {"S": "DRV003"},
    "warehouse_id": {"S": "WH003"},
    "first_name": {"S": "Kevin"},
    "last_name": {"S": "Wong"},
    "email": {"S": "kevin.wong@logistics.com"},
    "phone": {"S": "(310) 555-3003"},
    "license_number": {"S": "CA456789123"},
    "license_class": {"S": "CDL-A"},
    "license_expiry": {"S": "2027-02-28"},
    "hire_date": {"S": "2016-11-01"},
    "status": {"S": "Active"},
    "total_deliveries": {"N": "6234"},
    "on_time_rate_pct": {"N": "97.8"},
    "safety_score": {"N": "92"},
    "certifications": {"SS": ["Hazmat", "Tanker", "Port TWIC"]}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name drivers --item '{
    "driver_id": {"S": "DRV004"},
    "warehouse_id": {"S": "WH004"},
    "first_name": {"S": "Lisa"},
    "last_name": {"S": "Johnson"},
    "email": {"S": "lisa.johnson@logistics.com"},
    "phone": {"S": "(312) 555-4004"},
    "license_number": {"S": "IL789123456"},
    "license_class": {"S": "CDL-B"},
    "license_expiry": {"S": "2026-05-20"},
    "hire_date": {"S": "2020-02-10"},
    "status": {"S": "Active"},
    "total_deliveries": {"N": "2156"},
    "on_time_rate_pct": {"N": "99.5"},
    "safety_score": {"N": "99"},
    "certifications": {"SS": ["Refrigerated"]}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name drivers --item '{
    "driver_id": {"S": "DRV005"},
    "warehouse_id": {"S": "WH005"},
    "first_name": {"S": "Carlos"},
    "last_name": {"S": "Martinez"},
    "email": {"S": "carlos.martinez@logistics.com"},
    "phone": {"S": "(214) 555-5005"},
    "license_number": {"S": "TX321654987"},
    "license_class": {"S": "CDL-A"},
    "license_expiry": {"S": "2025-09-10"},
    "hire_date": {"S": "2017-08-25"},
    "status": {"S": "Active"},
    "total_deliveries": {"N": "5678"},
    "on_time_rate_pct": {"N": "98.2"},
    "safety_score": {"N": "94"},
    "certifications": {"SS": ["Hazmat", "Doubles/Triples", "Oversized"]}
}'

# ============================================================================
# INSERT FLEET VEHICLES
# ============================================================================
echo "Inserting fleet data..."

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name fleet --item '{
    "vehicle_id": {"S": "VEH001"},
    "warehouse_id": {"S": "WH001"},
    "vehicle_type": {"S": "Semi-Truck"},
    "make": {"S": "Freightliner"},
    "model": {"S": "Cascadia"},
    "year": {"N": "2022"},
    "vin": {"S": "3AKJHHDR5NSNA1234"},
    "license_plate": {"S": "NJ-TR-1001"},
    "capacity_lbs": {"N": "45000"},
    "capacity_cubic_ft": {"N": "3000"},
    "fuel_type": {"S": "Diesel"},
    "mpg": {"N": "7.2"},
    "current_mileage": {"N": "125000"},
    "status": {"S": "Active"},
    "last_maintenance_date": {"S": "2025-01-05"},
    "next_maintenance_due": {"S": "2025-04-05"},
    "gps_enabled": {"BOOL": true},
    "eld_device_id": {"S": "ELD-NE-001"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name fleet --item '{
    "vehicle_id": {"S": "VEH002"},
    "warehouse_id": {"S": "WH002"},
    "vehicle_type": {"S": "Box Truck"},
    "make": {"S": "International"},
    "model": {"S": "MV607"},
    "year": {"N": "2023"},
    "vin": {"S": "3HAMMAAR4NL567890"},
    "license_plate": {"S": "GA-BX-2002"},
    "capacity_lbs": {"N": "16000"},
    "capacity_cubic_ft": {"N": "1200"},
    "fuel_type": {"S": "Diesel"},
    "mpg": {"N": "12.5"},
    "current_mileage": {"N": "45000"},
    "status": {"S": "Active"},
    "last_maintenance_date": {"S": "2024-12-15"},
    "next_maintenance_due": {"S": "2025-03-15"},
    "gps_enabled": {"BOOL": true},
    "eld_device_id": {"S": "ELD-SE-002"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name fleet --item '{
    "vehicle_id": {"S": "VEH003"},
    "warehouse_id": {"S": "WH003"},
    "vehicle_type": {"S": "Semi-Truck"},
    "make": {"S": "Peterbilt"},
    "model": {"S": "579"},
    "year": {"N": "2021"},
    "vin": {"S": "1XPWD40X5ND234567"},
    "license_plate": {"S": "CA-TR-3003"},
    "capacity_lbs": {"N": "48000"},
    "capacity_cubic_ft": {"N": "3200"},
    "fuel_type": {"S": "Diesel"},
    "mpg": {"N": "6.8"},
    "current_mileage": {"N": "210000"},
    "status": {"S": "Active"},
    "last_maintenance_date": {"S": "2025-01-10"},
    "next_maintenance_due": {"S": "2025-04-10"},
    "gps_enabled": {"BOOL": true},
    "eld_device_id": {"S": "ELD-WC-003"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name fleet --item '{
    "vehicle_id": {"S": "VEH004"},
    "warehouse_id": {"S": "WH003"},
    "vehicle_type": {"S": "Refrigerated Truck"},
    "make": {"S": "Kenworth"},
    "model": {"S": "T680"},
    "year": {"N": "2023"},
    "vin": {"S": "1XKYD49X2NJ890123"},
    "license_plate": {"S": "CA-RF-3004"},
    "capacity_lbs": {"N": "42000"},
    "capacity_cubic_ft": {"N": "2800"},
    "fuel_type": {"S": "Diesel"},
    "mpg": {"N": "6.2"},
    "current_mileage": {"N": "78000"},
    "status": {"S": "Active"},
    "refrigeration_unit": {"S": "Carrier X4 7500"},
    "temp_range_min_f": {"N": "-20"},
    "temp_range_max_f": {"N": "70"},
    "last_maintenance_date": {"S": "2024-12-20"},
    "next_maintenance_due": {"S": "2025-03-20"},
    "gps_enabled": {"BOOL": true},
    "eld_device_id": {"S": "ELD-WC-004"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name fleet --item '{
    "vehicle_id": {"S": "VEH005"},
    "warehouse_id": {"S": "WH004"},
    "vehicle_type": {"S": "Sprinter Van"},
    "make": {"S": "Mercedes-Benz"},
    "model": {"S": "Sprinter 3500"},
    "year": {"N": "2024"},
    "vin": {"S": "W1Y4EBVY5NP456789"},
    "license_plate": {"S": "IL-VN-4005"},
    "capacity_lbs": {"N": "5500"},
    "capacity_cubic_ft": {"N": "530"},
    "fuel_type": {"S": "Diesel"},
    "mpg": {"N": "18.5"},
    "current_mileage": {"N": "12000"},
    "status": {"S": "Active"},
    "last_maintenance_date": {"S": "2024-11-30"},
    "next_maintenance_due": {"S": "2025-05-30"},
    "gps_enabled": {"BOOL": true},
    "eld_device_id": {"S": "ELD-MW-005"}
}'

# ============================================================================
# INSERT ROUTES
# ============================================================================
echo "Inserting route data..."

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name routes --item '{
    "route_id": {"S": "RT001"},
    "route_name": {"S": "Northeast Corridor Express"},
    "origin_warehouse_id": {"S": "WH001"},
    "destination_warehouse_id": {"S": "WH002"},
    "distance_miles": {"N": "870"},
    "estimated_duration_hours": {"N": "14"},
    "route_type": {"S": "Line Haul"},
    "frequency": {"S": "Daily"},
    "departure_time": {"S": "18:00"},
    "stops": {"L": [
        {"M": {"city": {"S": "Philadelphia"}, "state": {"S": "PA"}, "stop_type": {"S": "Fuel/Rest"}}},
        {"M": {"city": {"S": "Washington DC"}, "state": {"S": "DC"}, "stop_type": {"S": "Cross-dock"}}},
        {"M": {"city": {"S": "Richmond"}, "state": {"S": "VA"}, "stop_type": {"S": "Delivery"}}}
    ]},
    "toll_cost_estimate": {"N": "125.50"},
    "fuel_cost_estimate": {"N": "485.00"},
    "is_active": {"BOOL": true}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name routes --item '{
    "route_id": {"S": "RT002"},
    "route_name": {"S": "West Coast I-5 Run"},
    "origin_warehouse_id": {"S": "WH003"},
    "destination_warehouse_id": {"S": "WH003"},
    "distance_miles": {"N": "1380"},
    "estimated_duration_hours": {"N": "22"},
    "route_type": {"S": "Round Trip"},
    "frequency": {"S": "3x Weekly"},
    "departure_time": {"S": "04:00"},
    "stops": {"L": [
        {"M": {"city": {"S": "Bakersfield"}, "state": {"S": "CA"}, "stop_type": {"S": "Delivery"}}},
        {"M": {"city": {"S": "Fresno"}, "state": {"S": "CA"}, "stop_type": {"S": "Pickup"}}},
        {"M": {"city": {"S": "Sacramento"}, "state": {"S": "CA"}, "stop_type": {"S": "Cross-dock"}}},
        {"M": {"city": {"S": "Portland"}, "state": {"S": "OR"}, "stop_type": {"S": "Delivery"}}},
        {"M": {"city": {"S": "Seattle"}, "state": {"S": "WA"}, "stop_type": {"S": "Turnaround"}}}
    ]},
    "toll_cost_estimate": {"N": "45.00"},
    "fuel_cost_estimate": {"N": "780.00"},
    "is_active": {"BOOL": true}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name routes --item '{
    "route_id": {"S": "RT003"},
    "route_name": {"S": "Texas Triangle"},
    "origin_warehouse_id": {"S": "WH005"},
    "destination_warehouse_id": {"S": "WH005"},
    "distance_miles": {"N": "520"},
    "estimated_duration_hours": {"N": "9"},
    "route_type": {"S": "Regional Loop"},
    "frequency": {"S": "Daily"},
    "departure_time": {"S": "06:00"},
    "stops": {"L": [
        {"M": {"city": {"S": "Austin"}, "state": {"S": "TX"}, "stop_type": {"S": "Multi-stop Delivery"}}},
        {"M": {"city": {"S": "San Antonio"}, "state": {"S": "TX"}, "stop_type": {"S": "Multi-stop Delivery"}}},
        {"M": {"city": {"S": "Houston"}, "state": {"S": "TX"}, "stop_type": {"S": "Cross-dock"}}}
    ]},
    "toll_cost_estimate": {"N": "35.00"},
    "fuel_cost_estimate": {"N": "295.00"},
    "is_active": {"BOOL": true}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name routes --item '{
    "route_id": {"S": "RT004"},
    "route_name": {"S": "Midwest Express"},
    "origin_warehouse_id": {"S": "WH004"},
    "destination_warehouse_id": {"S": "WH001"},
    "distance_miles": {"N": "790"},
    "estimated_duration_hours": {"N": "13"},
    "route_type": {"S": "Line Haul"},
    "frequency": {"S": "Daily"},
    "departure_time": {"S": "20:00"},
    "stops": {"L": [
        {"M": {"city": {"S": "Cleveland"}, "state": {"S": "OH"}, "stop_type": {"S": "Fuel/Rest"}}},
        {"M": {"city": {"S": "Pittsburgh"}, "state": {"S": "PA"}, "stop_type": {"S": "Cross-dock"}}}
    ]},
    "toll_cost_estimate": {"N": "95.00"},
    "fuel_cost_estimate": {"N": "420.00"},
    "is_active": {"BOOL": true}
}'

# ============================================================================
# INSERT SHIPMENTS
# ============================================================================
echo "Inserting shipment data..."

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name shipments --item '{
    "shipment_id": {"S": "SHP-2025-00001"},
    "origin_warehouse_id": {"S": "WH003"},
    "destination_warehouse_id": {"S": "WH001"},
    "shipment_date": {"S": "2025-01-08"},
    "expected_delivery_date": {"S": "2025-01-12"},
    "actual_delivery_date": {"S": ""},
    "status": {"S": "In Transit"},
    "priority": {"S": "Standard"},
    "service_type": {"S": "Ground"},
    "total_weight_lbs": {"N": "12500"},
    "total_pieces": {"N": "48"},
    "total_pallets": {"N": "8"},
    "declared_value": {"N": "45000.00"},
    "freight_class": {"S": "70"},
    "customer_id": {"S": "CUST-1001"},
    "customer_name": {"S": "TechCorp Industries"},
    "customer_po": {"S": "PO-2025-78432"},
    "driver_id": {"S": "DRV003"},
    "vehicle_id": {"S": "VEH003"},
    "route_id": {"S": "RT002"},
    "special_instructions": {"S": "Fragile electronics - handle with care"},
    "requires_signature": {"BOOL": true},
    "is_hazmat": {"BOOL": false}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name shipments --item '{
    "shipment_id": {"S": "SHP-2025-00002"},
    "origin_warehouse_id": {"S": "WH001"},
    "destination_warehouse_id": {"S": "WH002"},
    "shipment_date": {"S": "2025-01-08"},
    "expected_delivery_date": {"S": "2025-01-09"},
    "actual_delivery_date": {"S": ""},
    "status": {"S": "In Transit"},
    "priority": {"S": "Express"},
    "service_type": {"S": "Next Day"},
    "total_weight_lbs": {"N": "3200"},
    "total_pieces": {"N": "15"},
    "total_pallets": {"N": "2"},
    "declared_value": {"N": "125000.00"},
    "freight_class": {"S": "85"},
    "customer_id": {"S": "CUST-1002"},
    "customer_name": {"S": "MedSupply Inc"},
    "customer_po": {"S": "PO-2025-91256"},
    "driver_id": {"S": "DRV001"},
    "vehicle_id": {"S": "VEH001"},
    "route_id": {"S": "RT001"},
    "special_instructions": {"S": "Medical supplies - temperature sensitive"},
    "requires_signature": {"BOOL": true},
    "is_hazmat": {"BOOL": false}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name shipments --item '{
    "shipment_id": {"S": "SHP-2025-00003"},
    "origin_warehouse_id": {"S": "WH005"},
    "destination_warehouse_id": {"S": "WH005"},
    "shipment_date": {"S": "2025-01-09"},
    "expected_delivery_date": {"S": "2025-01-09"},
    "actual_delivery_date": {"S": ""},
    "status": {"S": "Out for Delivery"},
    "priority": {"S": "Standard"},
    "service_type": {"S": "Same Day"},
    "total_weight_lbs": {"N": "8500"},
    "total_pieces": {"N": "120"},
    "total_pallets": {"N": "0"},
    "declared_value": {"N": "28500.00"},
    "freight_class": {"S": "55"},
    "customer_id": {"S": "CUST-1003"},
    "customer_name": {"S": "RetailMax Stores"},
    "customer_po": {"S": "PO-2025-45678"},
    "driver_id": {"S": "DRV005"},
    "vehicle_id": {"S": "VEH005"},
    "route_id": {"S": "RT003"},
    "special_instructions": {"S": "Multi-stop delivery - see manifest"},
    "requires_signature": {"BOOL": false},
    "is_hazmat": {"BOOL": false}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name shipments --item '{
    "shipment_id": {"S": "SHP-2025-00004"},
    "origin_warehouse_id": {"S": "WH002"},
    "destination_warehouse_id": {"S": "WH004"},
    "shipment_date": {"S": "2025-01-07"},
    "expected_delivery_date": {"S": "2025-01-09"},
    "actual_delivery_date": {"S": "2025-01-09"},
    "status": {"S": "Delivered"},
    "priority": {"S": "Standard"},
    "service_type": {"S": "Ground"},
    "total_weight_lbs": {"N": "22000"},
    "total_pieces": {"N": "85"},
    "total_pallets": {"N": "12"},
    "declared_value": {"N": "67500.00"},
    "freight_class": {"S": "65"},
    "customer_id": {"S": "CUST-1004"},
    "customer_name": {"S": "HomeGoods Warehouse"},
    "customer_po": {"S": "PO-2025-33221"},
    "driver_id": {"S": "DRV002"},
    "vehicle_id": {"S": "VEH002"},
    "route_id": {"S": "RT001"},
    "special_instructions": {"S": "Dock delivery only"},
    "requires_signature": {"BOOL": true},
    "is_hazmat": {"BOOL": false}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name shipments --item '{
    "shipment_id": {"S": "SHP-2025-00005"},
    "origin_warehouse_id": {"S": "WH003"},
    "destination_warehouse_id": {"S": "WH003"},
    "shipment_date": {"S": "2025-01-09"},
    "expected_delivery_date": {"S": "2025-01-10"},
    "actual_delivery_date": {"S": ""},
    "status": {"S": "Processing"},
    "priority": {"S": "High"},
    "service_type": {"S": "Expedited"},
    "total_weight_lbs": {"N": "5200"},
    "total_pieces": {"N": "25"},
    "total_pallets": {"N": "4"},
    "declared_value": {"N": "185000.00"},
    "freight_class": {"S": "92.5"},
    "customer_id": {"S": "CUST-1005"},
    "customer_name": {"S": "AutoParts Direct"},
    "customer_po": {"S": "PO-2025-88901"},
    "driver_id": {"S": ""},
    "vehicle_id": {"S": ""},
    "route_id": {"S": "RT002"},
    "special_instructions": {"S": "Auto parts - verify part numbers on delivery"},
    "requires_signature": {"BOOL": true},
    "is_hazmat": {"BOOL": false}
}'

# ============================================================================
# INSERT TRACKING EVENTS
# ============================================================================
echo "Inserting tracking events..."

# Events for SHP-2025-00001
aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00001"},
    "event_timestamp": {"S": "2025-01-08T08:30:00Z"},
    "event_type": {"S": "Picked Up"},
    "location": {"S": "Los Angeles, CA"},
    "facility": {"S": "WH003 - West Coast Mega Hub"},
    "description": {"S": "Shipment picked up from origin warehouse"},
    "updated_by": {"S": "System"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00001"},
    "event_timestamp": {"S": "2025-01-08T14:45:00Z"},
    "event_type": {"S": "Departed"},
    "location": {"S": "Los Angeles, CA"},
    "facility": {"S": "WH003 - West Coast Mega Hub"},
    "description": {"S": "Shipment departed origin facility"},
    "updated_by": {"S": "DRV003"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00001"},
    "event_timestamp": {"S": "2025-01-09T02:15:00Z"},
    "event_type": {"S": "In Transit"},
    "location": {"S": "Flagstaff, AZ"},
    "facility": {"S": ""},
    "description": {"S": "Shipment in transit - GPS update"},
    "updated_by": {"S": "GPS System"}
}'

# Events for SHP-2025-00002
aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00002"},
    "event_timestamp": {"S": "2025-01-08T16:00:00Z"},
    "event_type": {"S": "Picked Up"},
    "location": {"S": "Newark, NJ"},
    "facility": {"S": "WH001 - Northeast Distribution Center"},
    "description": {"S": "Express shipment picked up - priority handling"},
    "updated_by": {"S": "System"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00002"},
    "event_timestamp": {"S": "2025-01-08T18:30:00Z"},
    "event_type": {"S": "Departed"},
    "location": {"S": "Newark, NJ"},
    "facility": {"S": "WH001 - Northeast Distribution Center"},
    "description": {"S": "Departed for Atlanta - express route"},
    "updated_by": {"S": "DRV001"}
}'

# Events for SHP-2025-00004 (Delivered)
aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00004"},
    "event_timestamp": {"S": "2025-01-07T10:00:00Z"},
    "event_type": {"S": "Picked Up"},
    "location": {"S": "Atlanta, GA"},
    "facility": {"S": "WH002 - Southeast Fulfillment Hub"},
    "description": {"S": "Shipment picked up"},
    "updated_by": {"S": "System"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00004"},
    "event_timestamp": {"S": "2025-01-08T06:00:00Z"},
    "event_type": {"S": "Arrived"},
    "location": {"S": "Nashville, TN"},
    "facility": {"S": "Cross-dock facility"},
    "description": {"S": "Arrived at intermediate facility"},
    "updated_by": {"S": "System"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00004"},
    "event_timestamp": {"S": "2025-01-09T08:30:00Z"},
    "event_type": {"S": "Out for Delivery"},
    "location": {"S": "Chicago, IL"},
    "facility": {"S": "WH004 - Midwest Regional Center"},
    "description": {"S": "Shipment out for final delivery"},
    "updated_by": {"S": "DRV004"}
}'

aws dynamodb put-item --endpoint-url $ENDPOINT --table-name tracking_events --item '{
    "shipment_id": {"S": "SHP-2025-00004"},
    "event_timestamp": {"S": "2025-01-09T11:45:00Z"},
    "event_type": {"S": "Delivered"},
    "location": {"S": "Chicago, IL"},
    "facility": {"S": "Customer Location"},
    "description": {"S": "Delivered - Signed by: M. Thompson"},
    "updated_by": {"S": "DRV004"}
}'

echo "============================================"
echo "DynamoDB Logistics Database Initialized!"
echo "============================================"
echo ""
echo "Tables created:"
aws dynamodb list-tables --endpoint-url $ENDPOINT --output table
echo ""
echo "Run the following to verify data (from host):"
echo "  aws dynamodb scan --endpoint-url http://localhost:4566 --table-name warehouses --select COUNT"
echo "  aws dynamodb scan --endpoint-url http://localhost:4566 --table-name shipments --select COUNT"
echo ""

