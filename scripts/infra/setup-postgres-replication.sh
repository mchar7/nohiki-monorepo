#!/usr/bin/env bash
# =============================================================================
# NOHIKI - PostgreSQL CDC Replication Setup
# =============================================================================
#
# This script configures PostgreSQL for Debezium CDC (Change Data Capture).
# It is a ONE-TIME setup that must be run before deploying Kafka Connect.
#
# Prerequisites:
#   - PostgreSQL must be running and accessible
#   - You must have superuser access to PostgreSQL
#   - For Kubernetes: kubectl configured with correct context
#
# Usage:
#   Local (Docker Compose):
#     ./scripts/setup-postgres-replication.sh local
#
#   Kubernetes:
#     ./scripts/setup-postgres-replication.sh k8s [namespace]
#
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Default values
DEBEZIUM_USER="debezium"
DEBEZIUM_PASSWORD="debezium"
DATABASE_NAME="nohiki_db"
OUTBOX_SCHEMA="outbox_schema"
OUTBOX_TABLE="outbox"
PUBLICATION_NAME="nohiki_outbox_publication"
SLOT_NAME="nohiki_outbox_slot"

# Parse arguments
MODE="${1:-local}"
NAMESPACE="${2:-nohiki}"

run_psql_local() {
    docker exec -i nohiki-infra-postgres psql -U postgres -d "$DATABASE_NAME" "$@"
}

run_psql_k8s() {
    kubectl exec -i postgres-0 -n "$NAMESPACE" -- psql -U postgres -d "$DATABASE_NAME" "$@"
}

run_psql() {
    if [[ "$MODE" == "local" ]]; then
        run_psql_local "$@"
    else
        run_psql_k8s "$@"
    fi
}

check_wal_level() {
    log_info "Checking PostgreSQL wal_level..."
    local wal_level
    wal_level=$(run_psql -tAc "SHOW wal_level;")

    if [[ "$wal_level" != "logical" ]]; then
        log_error "wal_level is '$wal_level', expected 'logical'"
        log_error "PostgreSQL must be configured with wal_level=logical"

        if [[ "$MODE" == "local" ]]; then
            log_info "For Docker Compose, add to postgresql.conf or use command args:"
            log_info "  command: postgres -c wal_level=logical -c max_replication_slots=4 -c max_wal_senders=4"
        else
            log_info "For Kubernetes, update PostgreSQL ConfigMap and restart the pod"
        fi

        return 1
    fi

    log_info "✓ wal_level = logical"
    return 0
}

create_debezium_user() {
    log_info "Creating Debezium user..."

    run_psql <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DEBEZIUM_USER}') THEN
        CREATE ROLE ${DEBEZIUM_USER} WITH REPLICATION LOGIN PASSWORD '${DEBEZIUM_PASSWORD}';
        RAISE NOTICE 'Created user ${DEBEZIUM_USER}';
    ELSE
        RAISE NOTICE 'User ${DEBEZIUM_USER} already exists';
    END IF;
END
\$\$;
EOF

    log_info "✓ Debezium user ready"
}

create_outbox_schema() {
    log_info "Creating outbox schema and table..."

    run_psql <<EOF
-- Create outbox schema
CREATE SCHEMA IF NOT EXISTS ${OUTBOX_SCHEMA};

-- Create outbox table (matches OutboxWriter from R1.1)
CREATE TABLE IF NOT EXISTS ${OUTBOX_SCHEMA}.${OUTBOX_TABLE} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregatetype VARCHAR(255) NOT NULL,
    aggregateid VARCHAR(255) NOT NULL,
    type VARCHAR(255) NOT NULL,
    payload BYTEA NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    tracingspancontext VARCHAR(256)
);

-- Create index for timestamp-based queries (cleanup jobs)
CREATE INDEX IF NOT EXISTS idx_outbox_timestamp
    ON ${OUTBOX_SCHEMA}.${OUTBOX_TABLE}(timestamp);

-- Create index for aggregate lookups
CREATE INDEX IF NOT EXISTS idx_outbox_aggregate
    ON ${OUTBOX_SCHEMA}.${OUTBOX_TABLE}(aggregatetype, aggregateid);

COMMENT ON TABLE ${OUTBOX_SCHEMA}.${OUTBOX_TABLE} IS
    'Transactional outbox for CDC-based event publishing via Debezium';
EOF

    log_info "✓ Outbox schema and table ready"
}

grant_permissions() {
    log_info "Granting permissions to Debezium user..."

    run_psql <<EOF
-- Grant schema usage
GRANT USAGE ON SCHEMA ${OUTBOX_SCHEMA} TO ${DEBEZIUM_USER};

-- Grant SELECT on outbox table (Debezium only needs to read)
GRANT SELECT ON ${OUTBOX_SCHEMA}.${OUTBOX_TABLE} TO ${DEBEZIUM_USER};

-- Grant INSERT for heartbeat queries (optional, for connector health)
GRANT INSERT ON ${OUTBOX_SCHEMA}.${OUTBOX_TABLE} TO ${DEBEZIUM_USER};
EOF

    log_info "✓ Permissions granted"
}

create_publication() {
    log_info "Creating publication for CDC..."

    run_psql <<EOF
-- Drop existing publication if it exists (clean slate)
DROP PUBLICATION IF EXISTS ${PUBLICATION_NAME};

-- Create publication for outbox table only
CREATE PUBLICATION ${PUBLICATION_NAME} FOR TABLE ${OUTBOX_SCHEMA}.${OUTBOX_TABLE};
EOF

    log_info "✓ Publication '${PUBLICATION_NAME}' created"
}

drop_existing_slot() {
    log_info "Checking for existing replication slot..."

    local slot_exists
    slot_exists=$(run_psql -tAc "SELECT COUNT(*) FROM pg_replication_slots WHERE slot_name = '${SLOT_NAME}';")

    if [[ "$slot_exists" -gt 0 ]]; then
        log_warn "Replication slot '${SLOT_NAME}' exists, dropping it..."
        run_psql -c "SELECT pg_drop_replication_slot('${SLOT_NAME}');" || true
        log_info "✓ Existing slot dropped"
    else
        log_info "✓ No existing slot to clean up"
    fi
}

verify_setup() {
    log_info "Verifying setup..."

    echo ""
    echo "=== PostgreSQL CDC Configuration ==="
    echo ""

    # Check wal_level
    local wal_level
    wal_level=$(run_psql -tAc "SHOW wal_level;")
    echo "wal_level: $wal_level"

    # Check max_replication_slots
    local max_slots
    max_slots=$(run_psql -tAc "SHOW max_replication_slots;")
    echo "max_replication_slots: $max_slots"

    # Check max_wal_senders
    local max_senders
    max_senders=$(run_psql -tAc "SHOW max_wal_senders;")
    echo "max_wal_senders: $max_senders"

    # Check Debezium user
    local user_exists
    user_exists=$(run_psql -tAc "SELECT COUNT(*) FROM pg_roles WHERE rolname = '${DEBEZIUM_USER}';")
    echo "debezium user exists: $([[ $user_exists -gt 0 ]] && echo 'yes' || echo 'no')"

    # Check publication
    local pub_exists
    pub_exists=$(run_psql -tAc "SELECT COUNT(*) FROM pg_publication WHERE pubname = '${PUBLICATION_NAME}';")
    echo "publication exists: $([[ $pub_exists -gt 0 ]] && echo 'yes' || echo 'no')"

    # Check outbox table
    local table_exists
    table_exists=$(run_psql -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '${OUTBOX_SCHEMA}' AND table_name = '${OUTBOX_TABLE}';")
    echo "outbox table exists: $([[ $table_exists -gt 0 ]] && echo 'yes' || echo 'no')"

    echo ""
    echo "==================================="
    echo ""

    if [[ "$wal_level" == "logical" && "$user_exists" -gt 0 && "$pub_exists" -gt 0 && "$table_exists" -gt 0 ]]; then
        log_info "✓ All checks passed! PostgreSQL is ready for Debezium CDC."
        return 0
    else
        log_error "Some checks failed. Please review the output above."
        return 1
    fi
}

print_usage() {
    echo "Usage: $0 <mode> [namespace]"
    echo ""
    echo "Modes:"
    echo "  local    - Configure PostgreSQL in Docker Compose (default)"
    echo "  k8s      - Configure PostgreSQL in Kubernetes"
    echo ""
    echo "Options:"
    echo "  namespace - Kubernetes namespace (default: nohiki)"
    echo ""
    echo "Examples:"
    echo "  $0 local"
    echo "  $0 k8s nohiki"
}

main() {
    echo ""
    echo "=============================================="
    echo "  Nohiki PostgreSQL CDC Replication Setup"
    echo "=============================================="
    echo ""

    if [[ "$MODE" == "-h" || "$MODE" == "--help" ]]; then
        print_usage
        exit 0
    fi

    if [[ "$MODE" != "local" && "$MODE" != "k8s" ]]; then
        log_error "Invalid mode: $MODE"
        print_usage
        exit 1
    fi

    log_info "Mode: $MODE"
    if [[ "$MODE" == "k8s" ]]; then
        log_info "Namespace: $NAMESPACE"
    fi
    echo ""

    # Step 1: Check wal_level (may require restart if not logical)
    if ! check_wal_level; then
        log_error "Please configure wal_level=logical and restart PostgreSQL"
        exit 1
    fi

    # Step 2: Create Debezium user
    create_debezium_user

    # Step 3: Create outbox schema and table
    create_outbox_schema

    # Step 4: Grant permissions
    grant_permissions

    # Step 5: Create publication
    create_publication

    # Step 6: Drop any existing replication slot (Debezium will create it)
    drop_existing_slot

    # Step 7: Verify setup
    verify_setup

    echo ""
    log_info "Setup complete! You can now deploy Kafka Connect with Debezium."
    log_info "The replication slot will be created automatically by Debezium."
    echo ""
}

main "$@"
