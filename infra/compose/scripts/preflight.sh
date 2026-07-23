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
TIMEOUT="${TIMEOUT:-timeout}"
COMPOSE_UP_TIMEOUT_SECONDS="${COMPOSE_UP_TIMEOUT_SECONDS:-900}"
VALIDATOR="${SCRIPT_DIR}/validate-llm-endpoints.py"
compose_provider=""

fail() {
    echo "preflight: $1" >&2
    echo "preflight: see infra/shared/secrets/README.md for provisioning." >&2
    exit 1
}

command -v "${CONTAINER_RUNTIME}" >/dev/null 2>&1 \
    || fail "container runtime '${CONTAINER_RUNTIME}' not found on PATH (set CONTAINER_RUNTIME)."
compose_version=$("${CONTAINER_RUNTIME}" compose version 2>/dev/null) \
    || fail "'${CONTAINER_RUNTIME} compose' is not available; install the Compose plugin."
case "${compose_version}" in
    *podman-compose*) compose_provider=podman-compose ;;
esac
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
recovery_plan=""
action_diagnostics_visible=""
action_pid=""
pending_signal=""
up_action=""
requested_up_services=""
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
    [ -z "${recovery_plan}" ] || rm -f "${recovery_plan}"
}
replay_action_diagnostics() {
    if [ "${action_diagnostics_visible}" = yes ] && [ -s "${diagnostics}" ]; then
        cat "${diagnostics}" >&2 || true
    fi
    action_diagnostics_visible=""
}

forward_signal() {
    signal=$1
    status=$2
    trap '' HUP INT TERM
    if [ -n "${action_pid}" ]; then
        kill -"${signal}" "-${action_pid}" 2>/dev/null \
            || kill -"${signal}" "${action_pid}" 2>/dev/null \
            || true
        wait "${action_pid}" 2>/dev/null || true
        action_pid=""
    fi
    replay_action_diagnostics
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
action_timeout_seconds=""

validate_action() {
    [ "$#" -gt 0 ] || return 0
    action=$1
    shift
    case "${action}" in
        up)
            case "${COMPOSE_UP_TIMEOUT_SECONDS}" in
                ""|*[!0-9]*) fail "COMPOSE_UP_TIMEOUT_SECONDS must be a positive integer" ;;
            esac
            [ "${COMPOSE_UP_TIMEOUT_SECONDS}" -gt 0 ] \
                || fail "COMPOSE_UP_TIMEOUT_SECONDS must be a positive integer"
            command -v "${TIMEOUT}" >/dev/null 2>&1 \
                || fail "timeout command '${TIMEOUT}' not found on PATH (set TIMEOUT)."
            timeout_version=$("${TIMEOUT}" --version 2>/dev/null) \
                || fail "timeout command '${TIMEOUT}' must be GNU coreutils (set TIMEOUT)."
            case "${timeout_version}" in
                *"GNU coreutils"*) ;;
                *) fail "timeout command '${TIMEOUT}' must be GNU coreutils (set TIMEOUT)." ;;
            esac
            action_timeout_seconds=${COMPOSE_UP_TIMEOUT_SECONDS}
            for argument in "$@"; do
                case "${argument}" in
                    -d|--detach) ;;
                    --build|--no-build) ;;
                    -*) fail "unsupported option for Compose up" ;;
                    *)
                        service_name "${argument}"
                        requested_up_services="${requested_up_services}${requested_up_services:+ }${argument}"
                        ;;
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

run_tracked_recovery_action() {
    pending_signal=""
    pending_status=""
    trap 'pending_signal=HUP; pending_status=129' HUP
    trap 'pending_signal=INT; pending_status=130' INT
    trap 'pending_signal=TERM; pending_status=143' TERM
    "${TIMEOUT}" --signal=TERM --kill-after=30s "${action_timeout_seconds}s" "$@" &
    action_pid=$!
    trap 'forward_signal HUP 129' HUP
    trap 'forward_signal INT 130' INT
    trap 'forward_signal TERM 143' TERM
    if [ -n "${pending_signal}" ]; then
        forward_signal "${pending_signal}" "${pending_status}"
    fi
    set +e
    wait "${action_pid}"
    recovery_status=$?
    set -e
    action_pid=""
    return "${recovery_status}"
}

run_tracked_action_compose() {
    if [ -n "${COMPOSE_PROFILE}" ]; then
        run_tracked_recovery_action \
            "${CONTAINER_RUNTIME}" compose --profile "${COMPOSE_PROFILE}" -f "${action_config}" "$@"
    else
        run_tracked_recovery_action "${CONTAINER_RUNTIME}" compose -f "${action_config}" "$@"
    fi
}

recover_podman_created_services() {
    [ "${compose_provider}" = podman-compose ] || return 1
    if ! run_tracked_action_compose ps --format \
        '{{index .Labels "io.podman.compose.service"}}|{{.Names}}|{{.State}}|{{.ExitCode}}|{{.Status}}' \
        >"${diagnostics}" 2>/dev/null; then
        return 1
    fi
    recovery_plan=$(mktemp "${compose_dir}/.nohiki-compose-recovery.XXXXXX") \
        || return 1
    chmod 0600 "${recovery_plan}" || return 1
    if ! run_tracked_recovery_action "${PYTHON}" -c '
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as stream:
    document = yaml.safe_load(stream)
if not isinstance(document, dict) or not isinstance(document.get("services"), dict):
    raise SystemExit(2)
services = document["services"]
states = {}
with open(sys.argv[2], encoding="utf-8") as stream:
    for raw_line in stream:
        service, container, state, exit_code, status = raw_line.rstrip("\n").split("|", 4)
        if service and container:
            states.setdefault(service, []).append(
                (container, state.lower(), exit_code, status.lower())
            )

def dependencies(service):
    description = services.get(service, {})
    depends_on = description.get("depends_on", {}) if isinstance(description, dict) else {}
    if isinstance(depends_on, list):
        return ((dependency, "service_started") for dependency in depends_on)
    if isinstance(depends_on, dict):
        return (
            (
                dependency,
                details.get("condition", "service_started")
                if isinstance(details, dict)
                else "service_started",
            )
            for dependency, details in depends_on.items()
        )
    raise SystemExit(2)

requested = set(sys.argv[3].split())
if not requested.issubset(services):
    raise SystemExit(3)
active_profile = sys.argv[4]
if requested:
    roots = requested
else:
    roots = {
        service
        for service, description in services.items()
        if isinstance(description, dict)
        and (
            not description.get("profiles")
            or active_profile in description.get("profiles", ())
        )
    }
if not roots:
    raise SystemExit(3)
scope = set()
visiting = set()

def collect_scope(service):
    if service in visiting:
        raise SystemExit(3)
    if service in scope:
        return
    visiting.add(service)
    for dependency, _condition in dependencies(service):
        collect_scope(dependency)
    visiting.remove(service)
    scope.add(service)

for service in roots:
    collect_scope(service)

def collect_requirements(service, seen, requirements):
    if service in seen:
        return
    seen.add(service)
    for dependency, condition in dependencies(service):
        if condition not in {
            "service_completed_successfully",
            "service_healthy",
            "service_started",
        }:
            raise SystemExit(2)
        requirements.setdefault(dependency, set()).add(condition)
        collect_requirements(dependency, seen, requirements)


def condition_met(condition, records):
    if condition == "service_completed_successfully":
        return all(
            state == "exited" and exit_code == "0"
            for _container, state, exit_code, _status in records
        )
    if condition == "service_healthy":
        return all(
            state == "running" and "(healthy)" in status
            for _container, state, _exit_code, status in records
        )
    return all(state == "running" for _container, state, _exit_code, _status in records)

completed_services = set()
healthy_required = set()
started_required = set()
for dependent in scope:
    for dependency, condition in dependencies(dependent):
        if condition == "service_completed_successfully":
            completed_services.add(dependency)
        elif condition == "service_healthy":
            healthy_required.add(dependency)
        else:
            started_required.add(dependency)

def is_one_shot(service):
    description = services[service]
    restart = description.get("restart") if isinstance(description, dict) else None
    return service in completed_services or restart in ("no", False)

created = []
for service in services:
    if service not in scope:
        continue
    records = states.get(service)
    if not records:
        raise SystemExit(3)
    if any(state == "created" for _container, state, _exit_code, _status in records):
        if any(state != "created" for _container, state, _exit_code, _status in records):
            raise SystemExit(3)
        created.append(service)
    elif is_one_shot(service):
        if any(
            state != "exited" or exit_code != "0"
            for _container, state, exit_code, _status in records
        ):
            raise SystemExit(3)
    elif any(state != "running" for _container, state, _exit_code, _status in records):
        raise SystemExit(3)
    elif service in healthy_required and any(
        "(healthy)" not in status
        for _container, _state, _exit_code, status in records
    ):
        raise SystemExit(3)
if not created or (requested and requested.isdisjoint(created)):
    raise SystemExit(3)
created_set = set(created)
ordered_created = []
ordered = set()
ordering = set()

def order_created(service):
    if service in ordering:
        raise SystemExit(3)
    if service in ordered:
        return
    ordering.add(service)
    for dependency, _condition in dependencies(service):
        if dependency in created_set:
            order_created(dependency)
    ordering.remove(service)
    ordered.add(service)
    ordered_created.append(service)

for service in created:
    order_created(service)
created = ordered_created

expected = {}
operations = []
for service in created:
    requirements = {}
    collect_requirements(service, set(), requirements)
    for dependency, conditions in requirements.items():
        records = states.get(dependency)
        if not records:
            raise SystemExit(3)
        if dependency in created_set:
            continue
        if not all(condition_met(condition, records) for condition in conditions):
            raise SystemExit(3)
    lifecycle = "oneshot" if is_one_shot(service) else "running"
    if lifecycle == "oneshot" and (
        service in healthy_required or service in started_required
    ):
        raise SystemExit(3)
    health = "healthy" if service in healthy_required else "started"
    records = states[service]
    expected[service] = (len(records), lifecycle, health)
    operations.append(("recover", service, ""))
    containers = " ".join(
        container for container, _state, _exit_code, _status in records
    )
    if lifecycle == "oneshot":
        operations.append(("wait", "exited", containers))
    elif health == "healthy":
        operations.append(("wait", "healthy", containers))
    elif service in started_required:
        operations.append(("running", service, str(len(records))))
for service in services:
    if service in expected:
        count, lifecycle, health = expected[service]
        print(f"expected|{service}|{count}|{lifecycle}|{health}")
for operation in operations:
    print("|".join(operation))
' "${action_config}" "${diagnostics}" "${requested_up_services}" "${COMPOSE_PROFILE}" \
        >"${recovery_plan}" 2>/dev/null; then
        return 1
    fi
    [ -s "${recovery_plan}" ] || return 1
    while IFS='|' read -r plan_kind first second _rest; do
        case "${plan_kind}" in
            expected) ;;
            recover)
                [ -n "${first}" ] || return 1
                if ! run_tracked_action_compose \
                    up -d --force-recreate --no-deps "${first}"; then
                    return 1
                fi
                ;;
            wait)
                case "${first}" in
                    exited|healthy) ;;
                    *) return 1 ;;
                esac
                set -f
                set -- ${second}
                set +f
                [ "$#" -gt 0 ] || return 1
                if [ "${first}" = exited ]; then
                    container_count=$#
                    if ! run_tracked_recovery_action \
                        "${CONTAINER_RUNTIME}" wait --condition=exited "$@" >"${diagnostics}"; then
                        return 1
                    fi
                    waited_count=0
                    while IFS= read -r exit_code; do
                        [ "${exit_code}" = 0 ] || return 1
                        waited_count=$((waited_count + 1))
                    done <"${diagnostics}"
                    [ "${waited_count}" -eq "${container_count}" ] || return 1
                elif ! run_tracked_recovery_action \
                    "${CONTAINER_RUNTIME}" wait --condition=healthy "$@" >/dev/null; then
                    return 1
                fi
                ;;
            running)
                [ -n "${first}" ] && [ -n "${second}" ] || return 1
                if ! run_tracked_action_compose ps --format \
                    '{{index .Labels "io.podman.compose.service"}}|{{.Names}}|{{.State}}|{{.ExitCode}}|{{.Status}}' \
                    >"${diagnostics}" 2>/dev/null; then
                    return 1
                fi
                if ! run_tracked_recovery_action "${PYTHON}" -c '
import sys

service = sys.argv[2]
expected_count = int(sys.argv[3])
records = 0
with open(sys.argv[1], encoding="utf-8") as stream:
    for raw_line in stream:
        current, _container, state, _exit_code, _status = raw_line.rstrip("\n").split("|", 4)
        if current != service:
            continue
        records += 1
        if state.lower() != "running":
            raise SystemExit(3)
if records != expected_count:
    raise SystemExit(3)
' "${diagnostics}" "${first}" "${second}" >/dev/null 2>&1; then
                    return 1
                fi
                ;;
            *) return 1 ;;
        esac
    done <"${recovery_plan}"
    if ! run_tracked_action_compose ps --format \
        '{{index .Labels "io.podman.compose.service"}}|{{.Names}}|{{.State}}|{{.ExitCode}}|{{.Status}}' \
        >"${diagnostics}" 2>/dev/null; then
        return 1
    fi
    run_tracked_recovery_action "${PYTHON}" -c '
import sys

expected = {}
with open(sys.argv[1], encoding="utf-8") as stream:
    for raw_line in stream:
        fields = raw_line.rstrip("\n").split("|")
        if fields[0] != "expected":
            continue
        _kind, service, count, lifecycle, health = fields
        expected[service] = (int(count), lifecycle, health)
states = {}
with open(sys.argv[2], encoding="utf-8") as stream:
    for raw_line in stream:
        service, container, state, exit_code, status = raw_line.rstrip("\n").split("|", 4)
        if service in expected:
            states.setdefault(service, []).append(
                (container, state.lower(), exit_code, status.lower())
            )
for service, (count, lifecycle, health) in expected.items():
    records = states.get(service, ())
    if len(records) != count:
        raise SystemExit(3)
    if lifecycle == "oneshot":
        if any(
            state != "exited" or exit_code != "0"
            for _container, state, exit_code, _status in records
        ):
            raise SystemExit(3)
    elif any(state != "running" for _container, state, _exit_code, _status in records):
        raise SystemExit(3)
    elif health == "healthy" and any(
        "(healthy)" not in status
        for _container, _state, _exit_code, status in records
    ):
        raise SystemExit(3)
' "${recovery_plan}" "${diagnostics}" >/dev/null 2>&1
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
    up_action=yes
    shift
    set -- up --force-recreate "$@"
fi
cd "${compose_dir}"
if [ -n "${COMPOSE_PROFILE}" ]; then
    set -- "${CONTAINER_RUNTIME}" compose --profile "${COMPOSE_PROFILE}" -f "${action_config}" "$@"
else
    set -- "${CONTAINER_RUNTIME}" compose -f "${action_config}" "$@"
fi
if [ -n "${action_timeout_seconds}" ]; then
    : >"${diagnostics}"
    action_diagnostics_visible=yes
    "${TIMEOUT}" --signal=TERM --kill-after=30s "${action_timeout_seconds}s" "$@" 2>"${diagnostics}" &
else
    "$@" &
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
attempt_podman_recovery=""
dependency_state_improper=""
if [ "${up_action}" = yes ]; then
    case "${status}" in
        124)
            attempt_podman_recovery=yes
            ;;
        125)
            while IFS= read -r diagnostic_line; do
                case "${diagnostic_line}" in
                    *"container state improper"*) dependency_state_improper=yes ;;
                esac
            done <"${diagnostics}"
            [ "${dependency_state_improper}" = yes ] && attempt_podman_recovery=yes
            ;;
    esac
fi
replay_action_diagnostics
if [ "${attempt_podman_recovery}" = yes ] \
    && recover_podman_created_services; then
    echo "preflight: recovered Created services after a podman-compose timeout/dependency-state failure." >&2
    status=0
fi
if [ "${status}" -eq 124 ]; then
    echo "preflight: Compose up exceeded ${action_timeout_seconds}s; inspect container health and service logs." >&2
fi
exit "${status}"
