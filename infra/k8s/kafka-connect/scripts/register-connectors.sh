#!/bin/bash
# Register Debezium CDC connectors using the shared DSN at
# /run/secrets/database/dsn. Services default to outbox mode; explicit WAL-mode
# services use a dedicated logical-message connector.
set -euo pipefail

CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
SECRETS_DIR="${SECRETS_DIR:-/run/secrets}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${CONFIG_DIR:-${SCRIPT_DIR}/../connectors}"

# Service-to-schema pairs mirror the Helm-generated KafkaConnector resources.
OUTBOX_CONNECTORS=(
    "user-auth-service:user_auth_schema"
    "user-pref-service:user_pref_schema"
    "user-upload-service:user_upload_schema"
    "user-entitlement-service:user_entitlement_schema"
    "job-query-composition-service:job_query_schema"
    "job-ingest-enrichment-service:job_ingest_enrichment_schema"
    "job-storage-service:job_storage_schema"
    "doc-template-service:doc_template_schema"
    "skill-graph-service:skill_graph_schema"
    "bff-service:bff_schema"
    "notification-service:notification_schema"
)

# Dedicated logical-message connectors: service:schema:resource-prefix.
WAL_CONNECTORS=(
    "job-correlation-evaluation-service:job_correlation_schema:job_correlation"
)

# Persisted connector identities used by the legacy Compose Kafka Connect image.
LEGACY_OUTBOX_CONNECTORS=(
    "nohiki-outbox-user_auth"
    "nohiki-outbox-user_pref"
    "nohiki-outbox-user_upload"
    "nohiki-outbox-user_entitlement"
    "nohiki-outbox-job_query"
    "nohiki-outbox-job_storage"
    "nohiki-outbox-job_correlation"
    "nohiki-outbox-job_ingest_enrichment"
    "nohiki-outbox-doc_render"
    "nohiki-outbox-doc_schema"
    "nohiki-outbox-doc_template"
    "nohiki-outbox-skill_graph"
    "nohiki-outbox-notification"
)

parse_dsn() {
    local dsn="$1"
    local -a parts

    mapfile -d '' -t parts < <(python3 - "$dsn" <<'PY'
import sys
from urllib.parse import unquote, urlsplit

parsed = urlsplit(sys.argv[1])
if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
    raise SystemExit("database DSN must use postgres://, postgresql://, or postgresql+asyncpg://")
if parsed.username is None or parsed.password is None or parsed.hostname is None:
    raise SystemExit("database DSN must include username, password, and host")

values = (
    unquote(parsed.username),
    unquote(parsed.password),
    parsed.hostname,
    str(parsed.port or 5432),
    unquote(parsed.path.lstrip("/")),
)
if not values[-1]:
    raise SystemExit("database DSN must include a database name")
sys.stdout.write("\0".join(values) + "\0")
PY
    )
    [[ ${#parts[@]} -eq 5 ]] || { echo "ERROR: invalid database DSN" >&2; return 1; }
    DB_USER="${parts[0]}"
    DB_PASS="${parts[1]}"
    DB_HOST="${parts[2]}"
    DB_PORT="${parts[3]}"
    DB_NAME="${parts[4]}"
}

# Connect's CreateConnectorRequest rejects unknown top-level fields, so drop all "_"-prefixed metadata keys
strip_metadata_keys() {
    python3 -c 'import sys, json; d = json.load(sys.stdin); print(json.dumps({k: v for k, v in d.items() if not k.startswith("_")}))'
}

build_connector_config() {
    local service_name="$1"
    local schema_name="$2"
    local connector_mode="${3:-outbox}"
    local db_prefix="${service_name%-service}"
    db_prefix="${db_prefix//-/_}"
    local resource_prefix="${4:-$db_prefix}"
    local template_file="${CONFIG_DIR}/${connector_mode}-connector-template.json"

    SERVICE_NAME="${service_name}" DB_PREFIX="${db_prefix}" RESOURCE_PREFIX="${resource_prefix}" SCHEMA_NAME="${schema_name}" \
    DATABASE_HOST="${DB_HOST}" DATABASE_PORT="${DB_PORT}" DATABASE_USER="${DB_USER}" \
    DATABASE_PASSWORD="${DB_PASS}" DATABASE_NAME="${DB_NAME}" \
    python3 - "${template_file}" <<'PY'
import json
import os
import re
import sys

with open(sys.argv[1], encoding="utf-8") as template:
    document = json.load(template)

replacements = {
    key: os.environ[key]
    for key in (
        "SERVICE_NAME", "DB_PREFIX", "RESOURCE_PREFIX", "SCHEMA_NAME", "DATABASE_HOST",
        "DATABASE_PORT", "DATABASE_USER", "DATABASE_PASSWORD", "DATABASE_NAME",
    )
}

MARKER_RE = re.compile("|".join(re.escape(marker) for marker in replacements))

def substitute(value):
    if isinstance(value, str):
        return MARKER_RE.sub(lambda match: replacements[match.group(0)], value)
    if isinstance(value, list):
        return [substitute(item) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item) for key, item in value.items() if not key.startswith("_")}
    return value

json.dump(substitute(document), sys.stdout)
PY
}

check_replication_slot_health() {
    local slot_name="$1"
    local slot_exists
    slot_exists=$(PGPASSWORD="${DB_PASS}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
        -t -A -c "SELECT count(*) FROM pg_replication_slots WHERE slot_name = '${slot_name}';" 2>/dev/null || echo "0")

    if [[ "$slot_exists" == "1" ]]; then
        echo "active"
    else
        echo "missing"
    fi
}


register_connector() {
    local connector_name="$1"
    local config="$2"
    local config_only
    config_only=$(echo "$config" | python3 -c "import sys, json; d=json.load(sys.stdin); print(json.dumps(d['config']))")

    # Extract slot name from config for health checking
    local slot_name
    slot_name=$(echo "$config_only" | python3 -c "import sys,json; print(json.load(sys.stdin).get('slot.name',''))" 2>/dev/null || echo "")

    # Check if connector exists and has matching topic.prefix (immutable field)
    if curl -sf "${CONNECT_URL}/connectors/${connector_name}" > /dev/null 2>&1; then
        # Check connector state - UNASSIGNED means CDC is broken
        local connector_state
        connector_state=$(curl -sf "${CONNECT_URL}/connectors/${connector_name}/status" | \
            python3 -c "import sys,json; print(json.load(sys.stdin).get('connector',{}).get('state','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")

        # Check replication slot health if slot name is known
        local slot_health="active"
        if [[ -n "$slot_name" ]]; then
            slot_health=$(check_replication_slot_health "$slot_name")
        fi

        # Recreate broken connectors or connectors whose replication slot disappeared.
        if [[ "$connector_state" == "UNASSIGNED" ]] || [[ "$slot_health" == "missing" ]]; then
            echo "Recreating ${connector_name} (state=${connector_state}, slot=${slot_health})..."
            curl -sf -X DELETE "${CONNECT_URL}/connectors/${connector_name}" > /dev/null
            sleep 2
        else
            local current_prefix expected_prefix
            current_prefix=$(curl -sf "${CONNECT_URL}/connectors/${connector_name}/config" | python3 -c "import sys,json; print(json.load(sys.stdin).get('topic.prefix',''))" 2>/dev/null || echo "")
            expected_prefix=$(echo "$config_only" | python3 -c "import sys,json; print(json.load(sys.stdin).get('topic.prefix',''))")

            if [[ "$current_prefix" == "$expected_prefix" ]]; then
                printf '%s' "${config_only}" | curl -sf -X PUT -H "Content-Type: application/json" \
                    "${CONNECT_URL}/connectors/${connector_name}/config" --data-binary @- > /dev/null && return 0
            fi
            echo "Recreating ${connector_name} (topic.prefix mismatch)..."
            curl -s -X DELETE "${CONNECT_URL}/connectors/${connector_name}" > /dev/null
            sleep 2
        fi
    fi

    printf '%s' "${config}" | curl -sf -X POST -H "Content-Type: application/json" \
        "${CONNECT_URL}/connectors" --data-binary @- > /dev/null
}

delete_legacy_connector() {
    local connector_name="$1"
    local status

    if ! status=$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE \
        "${CONNECT_URL}/connectors/${connector_name}"); then
        echo "ERROR: failed to delete legacy connector ${connector_name}" >&2
        return 1
    fi

    case "$status" in
        2??) echo "Deleted legacy connector ${connector_name}" ;;
        404) ;;
        *)
            echo "ERROR: failed to delete legacy connector ${connector_name} (HTTP ${status})" >&2
            return 1
            ;;
    esac
}

cleanup_legacy_replication_resources() {
    local connector_name="$1"
    local suffix="${connector_name#nohiki-outbox-}"
    local slot_name="nohiki_outbox_slot_${suffix}"
    local publication_name="nohiki_outbox_pub_${suffix}"
    local slot_state

    # Only callers iterating LEGACY_OUTBOX_CONNECTORS may supply resource suffixes.
    [[ "$connector_name" == nohiki-outbox-* && "$suffix" =~ ^[a-z0-9_]+$ ]] || {
        echo "ERROR: invalid legacy connector name ${connector_name}" >&2
        return 1
    }

    slot_state=$(PGPASSWORD="${DB_PASS}" psql -X -v ON_ERROR_STOP=1 \
        -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
        -t -A \
        -c "SELECT CASE WHEN active THEN 'active' ELSE 'inactive' END FROM pg_replication_slots WHERE slot_name = '${slot_name}';")

    case "$slot_state" in
        active)
            echo "ERROR: legacy replication slot ${slot_name} is still active" >&2
            return 1
            ;;
        inactive)
            PGPASSWORD="${DB_PASS}" psql -X -v ON_ERROR_STOP=1 \
                -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
                -c "SELECT pg_drop_replication_slot('${slot_name}');" > /dev/null
            ;;
        '') ;;
        *)
            echo "ERROR: unexpected state for legacy replication slot ${slot_name}: ${slot_state}" >&2
            return 1
            ;;
    esac

    PGPASSWORD="${DB_PASS}" psql -X -v ON_ERROR_STOP=1 \
        -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
        -c "DROP PUBLICATION IF EXISTS \"${publication_name}\";" > /dev/null
}

register_qdrant_sink_connector() {
    local connector_file="${CONFIG_DIR}/qdrant-embedding-sink.json"
    if [[ ! -f "$connector_file" ]]; then
        echo "Qdrant sink connector config not found at ${connector_file}, skipping"
        return 0
    fi

    echo "Registering Qdrant embedding sink connector..."
    local config
    config=$(cat "$connector_file" | strip_metadata_keys)

    register_connector "qdrant-embedding-sink" "$config"
    echo "Qdrant embedding sink connector registered"
}

usage() {
    cat >&2 <<'EOF'
Usage: register-connectors.sh [register|migrate-legacy]

  register        Register/update the outbox, WAL-message, and sink connectors
                  (default). Idempotent and non-destructive; safe on every startup.
  migrate-legacy  DESTRUCTIVE. Delete the legacy Compose connector identities
                  and drop their replication slots/publications, then register.
                  Run explicitly during migration only, NEVER at startup.
EOF
}

register_all() {
    for connector in "${OUTBOX_CONNECTORS[@]}"; do
        service_name="${connector%%:*}"
        schema_name="${connector#*:}"
        register_connector "${service_name}-outbox" "$(build_connector_config "$service_name" "$schema_name")"
    done
    for connector in "${WAL_CONNECTORS[@]}"; do
        service_name="${connector%%:*}"
        remainder="${connector#*:}"
        schema_name="${remainder%%:*}"
        resource_prefix="${remainder#*:}"
        register_connector "${service_name}-wal" \
            "$(build_connector_config "$service_name" "$schema_name" wal "$resource_prefix")"
    done
    register_qdrant_sink_connector
}

migrate_legacy() {
    echo "Migrating off legacy connector identities (destructive)..."
    for connector_name in "${LEGACY_OUTBOX_CONNECTORS[@]}"; do
        delete_legacy_connector "$connector_name"
    done
    for connector_name in "${LEGACY_OUTBOX_CONNECTORS[@]}"; do
        cleanup_legacy_replication_resources "$connector_name"
    done
}

main() {
    local command="${1:-register}"
    local dsn_file="${SECRETS_DIR}/database/dsn"
    [[ -f "$dsn_file" ]] || { echo "ERROR: DSN not found at ${dsn_file}" >&2; exit 1; }

    parse_dsn "$(cat "$dsn_file")"

    case "$command" in
        register)
            echo "Registering connectors for ${DB_HOST}:${DB_PORT}/${DB_NAME}"
            register_all
            ;;
        migrate-legacy)
            echo "Registering connectors for ${DB_HOST}:${DB_PORT}/${DB_NAME}"
            migrate_legacy
            register_all
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            echo "ERROR: unknown command '${command}'" >&2
            usage
            exit 2
            ;;
    esac
}

main "$@"
