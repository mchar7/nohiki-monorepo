#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/../../.." && pwd)"
cd "$ROOT"

namespace="${K8S_NAMESPACE:-nohiki}"
expected_context="${K8S_LOCAL_CONTEXT:-}"
image_helper="infra/k8s/local/image_foundation.py"
digest_values="infra/k8s/gitops/platform/local/image-digests.values.yaml"
bootstrap_helper="infra/k8s/gitops/install/bootstrap.sh"
secret_helper="scripts/infra/validate_local_secret_sources.py"
secret_source_dir="${NOHIKI_LOCAL_SECRETS_DIR:-}"
gateway_helper="infra/k8s/local/gateway_proxy.py"
cluster_reset_helper="infra/k8s/local/cluster_reset.py"
registry_endpoint="${K8S_LOCAL_REGISTRY_ENDPOINT:-http://127.0.0.1:30500}"
mirror_config="${K3S_REGISTRIES_CONFIG:-/etc/rancher/k3s/registries.yaml}"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_file() {
    [[ -f "$1" ]] || fail "required lifecycle helper is absent: $1"
}
validate_secret_sources() {
    [[ -n "$secret_source_dir" ]] || fail "NOHIKI_LOCAL_SECRETS_DIR is required"
    [[ "$secret_source_dir" == /* ]] || fail "NOHIKI_LOCAL_SECRETS_DIR must be an absolute path"
    uv run python "$secret_helper" --secrets-dir "$secret_source_dir"
}


require_local_context() {
    [[ -n "$expected_context" ]] || fail "K8S_LOCAL_CONTEXT is required"
    local current
    current="$(kubectl config current-context)"
    [[ "$current" == "$expected_context" ]] || \
        fail "current context '$current' does not equal K8S_LOCAL_CONTEXT '$expected_context'"
}

check_local_dns_and_ports() {
    uv run python -c '
import ipaddress, os, socket, sys
host = "nohiki.localhost"
addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
if not addresses or not all(ipaddress.ip_address(value).is_loopback for value in addresses):
    sys.exit(f"{host} must resolve only to loopback addresses, got {sorted(addresses)}")
for variable, default in (("K8S_GATEWAY_PORT", "8080"), ("K8S_REGISTRY_PORT", "5000")):
    port = int(os.environ.get(variable, default))
    with socket.socket() as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            sys.exit(f"localhost:{port} is already occupied; stop the managed proxy or conflicting process")
'
}

preflight() {
    [[ -n "$secret_source_dir" ]] || fail "NOHIKI_LOCAL_SECRETS_DIR is required"
    [[ "$secret_source_dir" == /* ]] || fail "NOHIKI_LOCAL_SECRETS_DIR must be an absolute path"
    for command in kubectl flux helm kustomize uv; do
        command -v "$command" >/dev/null || fail "required command is unavailable: $command"
    done
    require_file "$bootstrap_helper"
    require_file "$secret_helper"
    require_file "$image_helper"
    require_file "$gateway_helper"
    validate_secret_sources
    require_local_context
    check_local_dns_and_ports

    NOHIKI_CLUSTER=local "$bootstrap_helper" --validate
    uv run python "$image_helper" validate
    uv run python "$image_helper" mirror-preflight \
        --config "$mirror_config" --endpoint "$registry_endpoint"
    kustomize build infra/k8s/gitops/clusters/local >/dev/null
    helm template nohiki-foundation infra/k8s/helm-foundation \
        --namespace nohiki-foundation >/dev/null
    uv run --project scripts/util/health_check health-check inventory --target k8s --json >/dev/null
    printf 'Local Kubernetes preflight passed (read-only).\n'
}

bootstrap() {
    preflight
    # Revalidate the Secret trust boundary immediately before the sole bootstrap mutation.
    validate_secret_sources
    NOHIKI_CLUSTER=local "$bootstrap_helper" --execute
}

publish() {
    require_file "$image_helper"
    require_local_context
    wait_ready registry
    local branch="${NOHIKI_RUNTIME_CONTROL_BRANCH:-}"
    local reviewed="${NOHIKI_REVIEWED_TOPIC_SHA:-}"
    local artifact="infra/k8s/gitops/platform/local/image-digests.values.yaml"
    local current head remote runtime tmp_json tmp_values artifact_hash after
    [[ "$branch" =~ ^runtime-control/local/[a-z0-9][a-z0-9._-]*$ ]] || \
        fail "NOHIKI_RUNTIME_CONTROL_BRANCH is not an approved local runtime-control branch"
    [[ "$reviewed" =~ ^[0-9a-f]{40}$ ]] || fail "NOHIKI_REVIEWED_TOPIC_SHA must be a full Git SHA"
    current="$(git branch --show-current)"
    head="$(git rev-parse HEAD)"
    [[ "$current" == "$branch" ]] || fail "current branch '$current' does not equal '$branch'"
    [[ "$head" == "$reviewed" ]] || fail "HEAD does not equal NOHIKI_REVIEWED_TOPIC_SHA"
    remote="$(git ls-remote --heads origin "refs/heads/$branch" | cut -f1)"
    [[ "$remote" == "$reviewed" ]] || fail "remote runtime-control branch does not equal reviewed SHA"

    local -a changed
    mapfile -t changed < <({ git diff --name-only HEAD; git ls-files --others --exclude-standard; } | sort -u)
    local path
    for path in "${changed[@]}"; do
        [[ "$path" == "$artifact" ]] || fail "publish refuses unrelated worktree change: $path"
    done

    runtime="${CONTAINER_RUNTIME:-docker}"
    uv run python "$image_helper" build --runtime "$runtime"
    tmp_json="$(mktemp)"
    tmp_values="$(mktemp)"
    local cleanup
    printf -v cleanup 'rm -f %q %q' "$tmp_json" "$tmp_values"
    # Expand now because publish locals are out of scope when the EXIT trap runs.
    # shellcheck disable=SC2064
    trap "$cleanup" EXIT
    trap 'exit 130' INT TERM
    uv run python "$image_helper" publish --runtime "$runtime" --digests "$tmp_json"
    uv run python "$image_helper" render-values --digests "$tmp_json" >"$tmp_values"
    artifact_hash="$(git hash-object "$tmp_values")"
    printf 'Generated %s (Git blob %s); image references are redacted.\n' "$artifact" "$artifact_hash"
    if [[ -f "$artifact" ]] && cmp -s "$tmp_values" "$artifact"; then
        printf 'Digest values already match reviewed runtime-control branch; no Git write required.\n'
        return
    fi
    install -m 0644 "$tmp_values" "$artifact"
    git add -- "$artifact"
    [[ "$(git diff --cached --name-only)" == "$artifact" ]] || fail "staged path allowlist violation"
    git commit -m "chore(k8s): publish local image digests" -- "$artifact"
    after="$(git rev-parse HEAD)"
    [[ "$(git diff-tree --no-commit-id --name-only -r "$after")" == "$artifact" ]] || \
        fail "publish commit changed a path outside the digest artifact"
    git push --force-with-lease="refs/heads/$branch:$reviewed" origin \
        "HEAD:refs/heads/$branch"
    printf 'Published digest artifact: before=%s after=%s path=%s\n' "$reviewed" "$after" "$artifact"
}

wait_ready() {
    local resource="kustomization/$1"
    local timeout="${K8S_RECONCILE_TIMEOUT:-20m}"
    kubectl -n flux-system wait --for=create "$resource" --timeout="$timeout"
    kubectl -n flux-system wait --for=condition=Ready=True "$resource" --timeout="$timeout"
}

reconcile() {
    require_local_context
    flux reconcile source git flux-system --namespace flux-system
    flux reconcile kustomization flux-system --namespace flux-system
    wait_ready flux-system
    local stack
    for stack in gateway-api-crds registry infrastructure runtime-secrets platform observability health-verification api-verification playwright-verification; do
        flux reconcile kustomization "$stack" --namespace flux-system
        wait_ready "$stack"
    done
}

verify_flux_observation() {
    local source_revision
    source_revision="$(kubectl -n flux-system get gitrepository flux-system -o jsonpath='{.status.artifact.revision}')"
    [[ -n "$source_revision" ]] || fail "Flux source has no artifact revision"
    local stack revision generation observed
    for stack in gateway-api-crds registry infrastructure runtime-secrets platform observability health-verification api-verification playwright-verification; do
        wait_ready "$stack"
        generation="$(kubectl -n flux-system get kustomization "$stack" -o jsonpath='{.metadata.generation}')"
        observed="$(kubectl -n flux-system get kustomization "$stack" -o jsonpath='{.status.observedGeneration}')"
        revision="$(kubectl -n flux-system get kustomization "$stack" -o jsonpath='{.status.lastAppliedRevision}')"
        [[ "$observed" == "$generation" ]] || fail "$stack has not observed its current generation"
        [[ "$revision" == "$source_revision" ]] || \
            fail "$stack is not applied at the current Flux source revision"
    done
}

verify() {
    require_local_context
    require_file "$gateway_helper"
    require_file "$image_helper"
    require_file scripts/infra/verify-k8s-jobs.py
    require_file infra/k8s/scripts/verify-migration-heads.py

    reconcile
    verify_flux_observation

    local evidence_dir inventory
    evidence_dir="${K8S_EVIDENCE_DIR:-.artifacts/k8s-local}"
    mkdir -p "$evidence_dir"
    inventory="$(mktemp)"
    trap 'uv run python "$gateway_helper" stop >/dev/null 2>&1 || true; rm -f "$inventory"' EXIT INT TERM
    uv run --package ci-checks ci-checks migration-truth \
        --repo-root . --namespace "$namespace" >"$inventory"
    uv run python infra/k8s/scripts/verify-migration-heads.py \
        --inventory "$inventory" --namespace "$namespace" \
        --evidence "$evidence_dir/migration-heads.json"

    uv run python "$gateway_helper" start
    uv run python scripts/infra/verify-k8s-jobs.py \
        --namespace nohiki-verification \
        --api-job nohiki-api-verification-v1 \
        --playwright-job nohiki-playwright-verification-v1 \
        --timeout-seconds 3600
    uv run python "$image_helper" status --digests "$digest_values" --registry "$registry_endpoint"
    uv run python "$image_helper" verify-pulls --digests "$digest_values"
    verify_flux_observation
    uv run python "$gateway_helper" stop
    trap - EXIT INT TERM
    rm -f "$inventory"
}

diagnostics() {
    require_local_context
    require_file "$image_helper"
    uv run --project scripts/util/health_check health-check inventory --target k8s --json
    flux get sources git --all-namespaces
    flux get kustomizations --all-namespaces
    flux get helmreleases --all-namespaces
    kubectl -n "$namespace" get gateway,httproute
    kubectl -n "$namespace" get deployments,statefulsets,daemonsets,jobs,pods
    uv run python "$image_helper" status --digests "$digest_values" --registry "$registry_endpoint"
    if [[ -f "${XDG_RUNTIME_DIR:-/tmp}/nohiki-k8s/gateway-proxy.json" ]]; then
        uv run python "$gateway_helper" status
    fi
}

mode="${1:-}"
[[ -n "$mode" ]] || fail "usage: $0 preflight|bootstrap|publish|reconcile|verify|diagnostics|factory-reset"
shift
case "$mode" in
    preflight) [[ $# -eq 0 ]] || fail "preflight accepts no arguments"; preflight ;;
    bootstrap) [[ $# -eq 0 ]] || fail "bootstrap accepts no arguments"; bootstrap ;;
    publish) [[ $# -eq 0 ]] || fail "publish accepts no arguments"; publish ;;
    reconcile) [[ $# -eq 0 ]] || fail "reconcile accepts no arguments"; reconcile ;;
    verify) [[ $# -eq 0 ]] || fail "verify accepts no arguments"; verify ;;
    diagnostics) [[ $# -eq 0 ]] || fail "diagnostics accepts no arguments"; diagnostics ;;
    factory-reset)
        require_file "$cluster_reset_helper"
        exec "$cluster_reset_helper" factory-reset "$@"
        ;;
    *) fail "unknown lifecycle mode: $mode" ;;
esac
