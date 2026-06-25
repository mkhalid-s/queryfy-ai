#!/bin/bash
# ============================================================================
# Cassandra Initialization Script
# Waits for Cassandra to be ready, then runs CQL init scripts
# ============================================================================

set -e

CASSANDRA_HOST=${CASSANDRA_HOST:-localhost}
CASSANDRA_PORT=${CASSANDRA_PORT:-9042}

echo "============================================"
echo "Initializing Cassandra Banking Database"
echo "============================================"

# Wait for Cassandra to be ready
echo "Waiting for Cassandra to be ready..."
until cqlsh $CASSANDRA_HOST $CASSANDRA_PORT -e 'describe cluster' > /dev/null 2>&1; do
    echo "Cassandra is not ready yet. Waiting..."
    sleep 5
done

echo "Cassandra is ready!"

# Run all CQL files in order
for cql_file in /docker-entrypoint-initdb.d/*.cql; do
    if [ -f "$cql_file" ]; then
        echo "Executing: $cql_file"
        cqlsh $CASSANDRA_HOST $CASSANDRA_PORT -f "$cql_file"
        echo "Completed: $cql_file"
    fi
done


echo "============================================"
echo "Cassandra Initialization Complete!"
echo "============================================"
echo ""
echo "Run the following to verify data:"
echo "  cqlsh localhost 9042 -e \"SELECT COUNT(*) FROM banking_db.customers;\""
echo "  cqlsh localhost 9042 -e \"SELECT * FROM banking_db.branches;\""
