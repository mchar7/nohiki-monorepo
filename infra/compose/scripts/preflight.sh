#!/bin/sh
# Render, validate, and optionally execute one immutable Compose configuration.
# Compose itself owns .env and interpolation parsing; temporary files are mode 0600.
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
COMPOSE_FILE="${COMPOSE_FILE:-${SCRIPT_DIR}/../docker-compose.yml}"
COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-}"
COMPOSE_PROFILE="${COMPOSE_PROFILE:-}"
SECRETS_DIR="${SECRETS_DIR:-${SCRIPT_DIR}/../../shared/secrets}"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-docker}"
PYTHON="${PYTHON:-python3}"
VALIDATOR="${SCRIPT_DIR}/validate-llm-endpoints.py"

fail() {
    echo "preflight: $1" >&2
    echo "preflight: see infra/shared/secrets/README.md for provisioning." >&2
    exit 1
}

command -v "${CONTAINER_RUNTIME}" >/dev/null 2>&1 \
    || fail "container runtime '${CONTAINER_RUNTIME}' not found on PATH (set CONTAINER_RUNTIME)."
"${CONTAINER_RUNTIME}" compose version >/dev/null 2>&1 \
    || fail "'${CONTAINER_RUNTIME} compose' is not available; install the Compose plugin."
command -v "${PYTHON}" >/dev/null 2>&1 \
    || fail "Python interpreter '${PYTHON}' not found on PATH (set PYTHON)."

compose_dir=$(CDPATH='' cd -- "$(dirname -- "${COMPOSE_FILE}")" && pwd) \
    || fail "Compose directory is unavailable."
override_source=""
if [ -n "${COMPOSE_OVERRIDE_FILE}" ]; then
    case "${COMPOSE_OVERRIDE_FILE}" in
        /*) override_source=${COMPOSE_OVERRIDE_FILE} ;;
        *) override_source=${compose_dir}/${COMPOSE_OVERRIDE_FILE} ;;
    esac
fi
base_snapshot=""
override_snapshot=""
rendered_config=""
diagnostics=""
action_config=""
action_pid=""
pending_signal=""
pending_status=""
# shellcheck disable=SC2329 # Invoked by the EXIT trap below.
cleanup() {
    trap '' HUP INT TERM
    trap - EXIT
    [ -z "${base_snapshot}" ] || rm -f "${base_snapshot}"
    [ -z "${override_snapshot}" ] || rm -f "${override_snapshot}"
    [ -z "${rendered_config}" ] || rm -f "${rendered_config}"
    [ -z "${diagnostics}" ] || rm -f "${diagnostics}"
    [ -z "${action_config}" ] || rm -f "${action_config}"
}
forward_signal() {
    signal=$1
    status=$2
    trap '' HUP INT TERM
    if [ -n "${action_pid}" ]; then
        kill -"${signal}" "${action_pid}" 2>/dev/null || true
        wait "${action_pid}" 2>/dev/null || true
        action_pid=""
    fi
    exit "${status}"
}

trap cleanup EXIT
trap 'forward_signal HUP 129' HUP
trap 'forward_signal INT 130' INT
trap 'forward_signal TERM 143' TERM
for argument in "$@"; do
    case "${argument}" in
        --env-file|--env-file=*|--env-from-file|--env-from-file=*)
            case "${1:-}" in
                run) fail "Compose run environment file options are not allowed" ;;
                *) fail "Compose environment file options are not allowed" ;;
            esac
            ;;
        -f|--file|--file=*|-f?*|--project-directory|--project-directory=*|--no-deps|--no-recreate)
            fail "configuration-mutating or dependency-skipping Compose options are not allowed"
            ;;
    esac
done

service_name() {
    case "$1" in
        ""|*[!A-Za-z0-9_.-]*|[.-]*) fail "invalid Compose service name" ;;
    esac
}

run_service=""
run_remove=""

validate_action() {
    [ "$#" -gt 0 ] || return 0
    action=$1
    shift
    case "${action}" in
        up)
            for argument in "$@"; do
                case "${argument}" in
                    -d|--detach|--build) ;;
                    -*) fail "unsupported option for Compose up" ;;
                    *) service_name "${argument}" ;;
                esac
            done
            ;;
        run)
            service=""
            run_remove=""
            while [ "$#" -gt 0 ]; do
                argument=$1
                shift
                if [ -n "${service}" ]; then
                    continue
                fi
                case "${argument}" in
                    --rm) run_remove=yes ;;
                    -e|--env)
                        [ "$#" -gt 0 ] || fail "Compose run environment option requires a value"
                        environment=$1
                        shift
                        case "${environment}" in
                            REFRESH_REASON=*) ;;
                            *) fail "Compose run environment override is not allowlisted" ;;
                        esac
                        ;;
                    --env=REFRESH_REASON=*) ;;
                    --env=*) fail "Compose run environment override is not allowlisted" ;;
                    -*) fail "unsupported option for Compose run" ;;
                    *)
                        service_name "${argument}"
                        service=${argument}
                        run_service=${argument}
                        ;;
                esac
            done
            [ -n "${service}" ] || fail "Compose run requires a service"
            [ "${run_remove}" = yes ] || fail "Compose run requires --rm to prevent stale one-off containers"
            ;;
        build)
            for argument in "$@"; do
                service_name "${argument}"
            done
            ;;
        down)
            for argument in "$@"; do
                case "${argument}" in
                    -v|--volumes) ;;
                    *) fail "unsupported option for Compose down" ;;
                esac
            done
            ;;
        logs)
            for argument in "$@"; do
                case "${argument}" in
                    -f|--follow) ;;
                    -*) fail "unsupported option for Compose logs" ;;
                    *) service_name "${argument}" ;;
                esac
            done
            ;;
        config|start|restart|exec|ps|pull|stop)
            fail "Compose action '${action}' is not allowed by the validated runtime gate"
            ;;
        *) fail "unsupported Compose action" ;;
    esac
}

validate_action "$@"

snapshot_source() {
    source_path=$1
    snapshot_path=$2
    [ -f "${source_path}" ] || fail "Compose source is unavailable."
    LC_ALL=C grep -Eq '^(include|"include"|'"'"'include'"'"')[[:space:]]*:' "${source_path}" \
        && fail "Compose include is not allowed; every source must be snapshotted and validated."
    cat "${source_path}" >"${snapshot_path}" \
        || fail "could not snapshot a Compose source."
}

base_snapshot=$(mktemp "${compose_dir}/.nohiki-compose-source.XXXXXX") \
    || fail "could not allocate a Compose source snapshot."
chmod 0600 "${base_snapshot}" \
    || fail "could not secure a Compose source snapshot."
snapshot_source "${COMPOSE_FILE}" "${base_snapshot}"
if [ -n "${override_source}" ]; then
    override_snapshot=$(mktemp "${compose_dir}/.nohiki-compose-source.XXXXXX") \
        || fail "could not allocate a Compose override snapshot."
    chmod 0600 "${override_snapshot}" \
        || fail "could not secure a Compose override snapshot."
    snapshot_source "${override_source}" "${override_snapshot}"
fi
if [ -n "${override_snapshot}" ]; then
    "${PYTHON}" "${VALIDATOR}" --validate-sources "${base_snapshot}" "${override_snapshot}" \
        || fail "Compose source provenance is invalid."
else
    "${PYTHON}" "${VALIDATOR}" --validate-sources "${base_snapshot}" \
        || fail "Compose source provenance is invalid."
fi

rendered_config=$(mktemp "${compose_dir}/.nohiki-compose-rendered.XXXXXX") \
    || fail "could not allocate a temporary Compose render."
diagnostics=$(mktemp "${compose_dir}/.nohiki-compose-diagnostics.XXXXXX") \
    || fail "could not allocate temporary Compose diagnostics."
chmod 0600 "${rendered_config}" "${diagnostics}" \
    || fail "could not secure temporary Compose files."

source_compose() {
    if [ -n "${override_snapshot}" ] && [ -n "${COMPOSE_PROFILE}" ]; then
        "${CONTAINER_RUNTIME}" compose --profile "${COMPOSE_PROFILE}" -f "${base_snapshot}" -f "${override_snapshot}" "$@"
    elif [ -n "${override_snapshot}" ]; then
        "${CONTAINER_RUNTIME}" compose -f "${base_snapshot}" -f "${override_snapshot}" "$@"
    elif [ -n "${COMPOSE_PROFILE}" ]; then
        "${CONTAINER_RUNTIME}" compose --profile "${COMPOSE_PROFILE}" -f "${base_snapshot}" "$@"
    else
        "${CONTAINER_RUNTIME}" compose -f "${base_snapshot}" "$@"
    fi
}


if ! (cd "${compose_dir}" && source_compose config >"${rendered_config}") 2>"${diagnostics}"; then
    fail "Compose configuration could not be rendered; renderer diagnostics were suppressed."
fi
if [ -n "${override_snapshot}" ]; then
    "${PYTHON}" "${VALIDATOR}" "${base_snapshot}" "${override_snapshot}" "${rendered_config}" \
        || fail "LLM provider/model endpoint mapping is invalid."
else
    "${PYTHON}" "${VALIDATOR}" "${base_snapshot}" "${rendered_config}" \
        || fail "LLM provider/model endpoint mapping is invalid."
fi

[ -d "${SECRETS_DIR}" ] \
    || fail "secrets directory not found at ${SECRETS_DIR}."
for category in database redis s3 jwt oauth jsearch llm gcp email qdrant s3-mlflow; do
    [ -d "${SECRETS_DIR}/${category}" ] \
        || fail "required secret directory missing: ${category}/ (under ${SECRETS_DIR})."
done
for required in database/dsn s3/rustfs-root.env; do
    [ -f "${SECRETS_DIR}/${required}" ] \
        || fail "required secret file missing: ${required} (under ${SECRETS_DIR})."
done

action_compose() {
    if [ -n "${COMPOSE_PROFILE}" ]; then
        "${CONTAINER_RUNTIME}" compose --profile "${COMPOSE_PROFILE}" -f "${action_config}" "$@"
    else
        "${CONTAINER_RUNTIME}" compose -f "${action_config}" "$@"
    fi
}

if [ "$#" -eq 0 ]; then
    echo "preflight: OK (runtime='${CONTAINER_RUNTIME}', secret contract present, endpoint contract valid)"
    exit 0
fi
action_config=$(mktemp "${compose_dir}/.nohiki-compose-action.XXXXXX") \
    || fail "could not allocate a temporary Compose action configuration."
chmod 0600 "${action_config}" \
    || fail "could not secure the temporary Compose action configuration."
"${PYTHON}" "${VALIDATOR}" --encode-action "${rendered_config}" "${action_config}" \
    || fail "could not encode the validated Compose action configuration."
trap 'pending_signal=HUP; pending_status=129' HUP
trap 'pending_signal=INT; pending_status=130' INT
trap 'pending_signal=TERM; pending_status=143' TERM
if [ "$1" = "run" ]; then
    action_compose up --force-recreate --no-start "${run_service}" > /dev/null 2>"${diagnostics}" &
    action_pid=$!
    trap 'forward_signal HUP 129' HUP
    trap 'forward_signal INT 130' INT
    trap 'forward_signal TERM 143' TERM
    if [ -n "${pending_signal}" ]; then
        forward_signal "${pending_signal}" "${pending_status}"
    fi
    set +e
    wait "${action_pid}"
    status=$?
    set -e
    action_pid=""
    [ "${status}" -eq 0 ] || fail "Compose run dependencies could not be recreated; diagnostics were suppressed."
    pending_signal=""
    pending_status=""
    trap 'pending_signal=HUP; pending_status=129' HUP
    trap 'pending_signal=INT; pending_status=130' INT
    trap 'pending_signal=TERM; pending_status=143' TERM
fi
if [ "$1" = "up" ]; then
    shift
    set -- up --force-recreate "$@"
fi
cd "${compose_dir}"
if [ -n "${COMPOSE_PROFILE}" ]; then
    "${CONTAINER_RUNTIME}" compose --profile "${COMPOSE_PROFILE}" -f "${action_config}" "$@" &
else
    "${CONTAINER_RUNTIME}" compose -f "${action_config}" "$@" &
fi
action_pid=$!
trap 'forward_signal HUP 129' HUP
trap 'forward_signal INT 130' INT
trap 'forward_signal TERM 143' TERM
if [ -n "${pending_signal}" ]; then
    forward_signal "${pending_signal}" "${pending_status}"
fi
set +e
wait "${action_pid}"
status=$?
set -e
action_pid=""
exit "${status}"
