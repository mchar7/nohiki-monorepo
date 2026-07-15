#!/bin/sh
# RustFS initialization script
# Creates buckets, policies, and service users with least-privilege access
#
# This script mirrors production IAM structure:
# - Each service has its own credentials
# - Each service has a policy scoped to only required buckets/operations
#
set -e

RUSTFS_HOST="${RUSTFS_HOST:-nohiki-infra-rustfs}"
RUSTFS_PORT="${RUSTFS_PORT:-9000}"
: "${RUSTFS_ROOT_USER:?not set; run the setup in infra/shared/secrets/README.md}"
: "${RUSTFS_ROOT_PASSWORD:?not set; run the setup in infra/shared/secrets/README.md}"

POLICIES_DIR="${POLICIES_DIR:-/policies}"

echo "Configuring RustFS alias..."
mc alias set rustfs "http://${RUSTFS_HOST}:${RUSTFS_PORT}" "${RUSTFS_ROOT_USER}" "${RUSTFS_ROOT_PASSWORD}"

echo "Creating buckets..."
mc mb --ignore-existing rustfs/nohiki-attachments
mc mb --ignore-existing rustfs/nohiki-templates
mc mb --ignore-existing rustfs/nohiki-tailored-docs
mc mb --ignore-existing rustfs/nohiki-ml-artifacts
mc mb --ignore-existing rustfs/nohiki-mlflow-artifacts

echo "Creating policies..."
for policy_file in "${POLICIES_DIR}"/*.json; do
    if [ -f "$policy_file" ]; then
        policy_name=$(basename "$policy_file" .json)
        echo "  Creating policy: ${policy_name}"
        mc admin policy create rustfs "${policy_name}" "${policy_file}" 2>/dev/null || \
            mc admin policy info rustfs "${policy_name}" >/dev/null 2>&1 || \
            { echo "Failed to create policy ${policy_name}"; exit 1; }
    fi
done

# Create service users with their policies
# Credentials are read from environment variables set by docker-compose
# Format: SVC_<SERVICE>_ACCESS_KEY, SVC_<SERVICE>_SECRET_KEY

create_service_user() {
    local service_name="$1"
    local policy_name="$2"
    local access_key_var="SVC_${service_name}_ACCESS_KEY"
    local secret_key_var="SVC_${service_name}_SECRET_KEY"

    eval "access_key=\${${access_key_var}:-}"
    eval "secret_key=\${${secret_key_var}:-}"

    if [ -z "$access_key" ] || [ -z "$secret_key" ]; then
        echo "  Skipping ${service_name}: credentials not provided"
        return 0
    fi

    echo "  Creating user: ${service_name}"

    # Create or update the user. A genuine failure must fail the init job; an
    # already-existing user is fine (mc upserts, but verify to be certain).
    if ! mc admin user add rustfs "${access_key}" "${secret_key}"; then
        mc admin user info rustfs "${access_key}" >/dev/null 2>&1 \
            || { echo "  ERROR: failed to create user ${service_name}" >&2; exit 1; }
    fi

    # Attach the policy. An already-in-effect association is success; anything
    # else is a real failure and must not be swallowed.
    attach_output=$(mc admin policy attach rustfs "${policy_name}" --user "${access_key}" 2>&1) \
        || echo "${attach_output}" | grep -q "already in effect" \
        || { echo "  ERROR: failed to attach ${policy_name} to ${service_name}: ${attach_output}" >&2; exit 1; }
}

echo "Creating service users..."
create_service_user "USER_UPLOAD" "user-upload-service"
create_service_user "BFF" "bff-service"
create_service_user "DOC_TEMPLATE" "doc-template-service"
create_service_user "DOC_CONTENT" "doc-content-service"
create_service_user "ML_COMPUTE" "ml-compute-service"
create_service_user "JOB_CORRELATION" "job-correlation-evaluation-service"
create_service_user "MLFLOW" "mlflow"

echo "RustFS initialization complete"
