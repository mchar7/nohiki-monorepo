#!/usr/bin/env bash
# One-time, local Flux bootstrap. Normal reconciliation must use the reconcile
# lifecycle command and must never invoke this script.

set -euo pipefail

readonly GITOPS_NAMESPACE="flux-system"
readonly FLUX_BOOTSTRAP_COMMIT_MESSAGE="chore(gitops): generate reviewed local Flux bootstrap"

BOOTSTRAP_TMP_ROOT=""
BOOTSTRAP_LOCK_FD=""
BOOTSTRAP_GIT_INDEX_LOCK=""

cleanup_bootstrap() {
  local status=$?
  if [[ -n "${BOOTSTRAP_GIT_INDEX_LOCK}" ]]; then
    rm -f -- "${BOOTSTRAP_GIT_INDEX_LOCK}"
  fi
  if [[ -n "${BOOTSTRAP_TMP_ROOT}" ]]; then
    rm -rf -- "${BOOTSTRAP_TMP_ROOT}"
  fi
  if [[ -n "${BOOTSTRAP_LOCK_FD}" ]]; then
    flock -u "${BOOTSTRAP_LOCK_FD}" 2>/dev/null || true
    exec {BOOTSTRAP_LOCK_FD}>&-
  fi
  exit "${status}"
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

require() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} is required (fail-closed)."
}

usage() {
  cat >&2 <<'USAGE'
Usage: infra/k8s/gitops/install/bootstrap.sh --validate|--dry-run|--execute

  --validate  Validate the reviewed runtime-control identity and pristine local
              Flux source state. Performs no Git or Kubernetes writes.
  --dry-run   Also render and validate the exact Flux output in a temporary
              directory. Performs no Git or Kubernetes writes.
  --execute   Generate, commit, and push the exact three bootstrap files, then
              perform the one-time cluster bootstrap. Never use for reconcile.
USAGE
}

parse_mode() {
  [[ $# -eq 1 ]] || { usage; return 2; }
  case "$1" in
    --validate | --dry-run | --execute) printf '%s\n' "$1" ;;
    *) usage; return 2 ;;
  esac
}

validate_slug() {
  local label="$1" value="$2"
  [[ "${value}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || fail "${label} contains unsupported characters."
}

flux_sync_url() {
  printf 'ssh://git@github.com/%s/%s.git\n' "$1" "$2"
}

validate_remote_origin() {
  local repo="$1" owner="$2" repository="$3" origin sync_url
  origin="$(git -C "${repo}" remote get-url origin 2>/dev/null)" || fail "Git remote 'origin' is required."
  sync_url="$(flux_sync_url "${owner}" "${repository}")"
  # The emitted Flux sync URL is itself an accepted origin: a worktree whose remote is exactly the
  # URL Flux syncs from must not be rejected. The https and SCP forms stay accepted as operator
  # input; only the emitted value is normalised to the ssh scheme Flux requires.
  case "${origin}" in
    "${sync_url}" | "${sync_url%.git}" | \
      "https://github.com/${owner}/${repository}" | "https://github.com/${owner}/${repository}.git" | \
      "git@github.com:${owner}/${repository}" | "git@github.com:${owner}/${repository}.git") ;;
    *) fail "Git remote 'origin' does not exactly match the declared GitHub owner/repository." ;;
  esac
}

generate_flux_output() {
  local output_dir="$1" cluster_path="$2" repository_url="$3" branch="$4"
  mkdir -p -- "${output_dir}"
  flux install --export >"${output_dir}/gotk-components.yaml"
  flux create source git flux-system \
    --url="${repository_url}" \
    --branch="${branch}" \
    --secret-ref=flux-system \
    --interval=1m \
    --export >"${output_dir}/gotk-sync.yaml"
  flux create kustomization flux-system \
    --source=GitRepository/flux-system \
    --path="./${cluster_path}" \
    --prune=true \
    --interval=10m \
    --export >>"${output_dir}/gotk-sync.yaml"
  cat >"${output_dir}/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - gotk-components.yaml
  - gotk-sync.yaml
YAML
}

assert_pristine_bootstrap_source() {
  local repo="$1" flux_dir="$2" state status
  state="$(classify_flux_state "${flux_dir}")" || exit 1
  [[ "${state}" == "absent" ]] ||
    fail "Flux bootstrap state is already complete; use normal reconcile instead of bootstrap."
  status="$(git -C "${repo}" status --porcelain=v1 --untracked-files=all)" || fail "cannot inspect Git worktree state."
  [[ -z "${status}" ]] || fail "Flux bootstrap requires a pristine reviewed worktree."
}

bound_kubectl() {
  python3 "${SNAPSHOT_HELPER}" exec-bound \
    "${BOOTSTRAP_KUBECONFIG}" "${BOOTSTRAP_KUBECONFIG_SHA256}" @KUBECONFIG@ -- \
    kubectl --kubeconfig=@KUBECONFIG@ --context="${BOOTSTRAP_CONTEXT}" "$@"
}

bound_flux() {
  python3 "${SNAPSHOT_HELPER}" exec-bound \
    "${BOOTSTRAP_KUBECONFIG}" "${BOOTSTRAP_KUBECONFIG_SHA256}" @KUBECONFIG@ -- \
    flux --kubeconfig=@KUBECONFIG@ --context="${BOOTSTRAP_CONTEXT}" "$@"
}

bound_age_recipient() {
  python3 "${SNAPSHOT_HELPER}" exec-bound \
    "${BOOTSTRAP_AGE_KEY}" "${BOOTSTRAP_AGE_KEY_SHA256}" @AGEKEY@ -- age-keygen -y @AGEKEY@
}

bound_kubectl_with_age() {
  python3 "${SNAPSHOT_HELPER}" exec-bound \
    "${BOOTSTRAP_KUBECONFIG}" "${BOOTSTRAP_KUBECONFIG_SHA256}" @KUBECONFIG@ \
    "${BOOTSTRAP_AGE_KEY}" "${BOOTSTRAP_AGE_KEY_SHA256}" @AGEKEY@ -- \
    kubectl --kubeconfig=@KUBECONFIG@ --context="${BOOTSTRAP_CONTEXT}" "$@"
}

assert_bound_cluster_identity() {
  local actual_context
  actual_context="$(bound_kubectl config current-context 2>/dev/null)" ||
    fail "cannot revalidate the descriptor-bound Kubernetes context."
  [[ "${actual_context}" == "${BOOTSTRAP_CONTEXT}" ]] ||
    fail "bound Kubernetes context changed during bootstrap."
}

assert_cluster_flux_absent() {
  local namespace
  assert_bound_cluster_identity
  namespace="$(bound_kubectl get namespace "${GITOPS_NAMESPACE}" --ignore-not-found -o name 2>/dev/null)" ||
    fail "cannot establish the bound cluster Flux state."
  [[ -z "${namespace}" ]] ||
    fail "cluster flux-system state already exists or is partial; use normal reconcile or recover it explicitly."
}

prepare_execute_snapshots() {
  local repo="$1" reviewed_sha="$2"
  local source_context derived_recipient policy_text line
  local -a reviewed_recipients=()
  require K8S_LOCAL_CONTEXT
  require KUBECONFIG
  require SOPS_AGE_KEY_FILE
  command -v python3 >/dev/null 2>&1 || fail "python3 is required for descriptor-safe bootstrap snapshots."
  command -v sha256sum >/dev/null 2>&1 || fail "sha256sum CLI not found."
  command -v age-keygen >/dev/null 2>&1 || fail "age-keygen CLI not found."

  BOOTSTRAP_CONTEXT="${K8S_LOCAL_CONTEXT}"
  readonly BOOTSTRAP_CONTEXT
  BOOTSTRAP_KUBECONFIG_SOURCE="${BOOTSTRAP_TMP_ROOT}/kubeconfig.source"
  BOOTSTRAP_KUBECONFIG_SOURCE_SHA256="$(python3 "${SNAPSHOT_HELPER}" snapshot-kubeconfig \
    "${KUBECONFIG}" "${BOOTSTRAP_KUBECONFIG_SOURCE}")"
  readonly BOOTSTRAP_KUBECONFIG_SOURCE BOOTSTRAP_KUBECONFIG_SOURCE_SHA256
  source_context="$(python3 "${SNAPSHOT_HELPER}" exec-bound \
    "${BOOTSTRAP_KUBECONFIG_SOURCE}" "${BOOTSTRAP_KUBECONFIG_SOURCE_SHA256}" @KUBECONFIG@ -- \
    kubectl --kubeconfig=@KUBECONFIG@ config current-context 2>/dev/null)" ||
    fail "cannot resolve the descriptor-bound Kubernetes context."
  [[ "${source_context}" == "${BOOTSTRAP_CONTEXT}" ]] ||
    fail "K8S_LOCAL_CONTEXT must exactly equal the snapshotted Kubernetes current-context."

  BOOTSTRAP_KUBECONFIG="${BOOTSTRAP_TMP_ROOT}/kubeconfig"
  python3 "${SNAPSHOT_HELPER}" exec-bound \
    "${BOOTSTRAP_KUBECONFIG_SOURCE}" "${BOOTSTRAP_KUBECONFIG_SOURCE_SHA256}" @KUBECONFIG@ -- \
    kubectl --kubeconfig=@KUBECONFIG@ --context="${BOOTSTRAP_CONTEXT}" \
    config view --raw --flatten --minify >"${BOOTSTRAP_KUBECONFIG}" ||
    fail "cannot create an immutable kubeconfig snapshot."
  [[ -s "${BOOTSTRAP_KUBECONFIG}" ]] || fail "immutable kubeconfig snapshot is empty."
  chmod 0600 -- "${BOOTSTRAP_KUBECONFIG}"
  BOOTSTRAP_KUBECONFIG_SHA256="$(sha256sum -- "${BOOTSTRAP_KUBECONFIG}")"
  BOOTSTRAP_KUBECONFIG_SHA256="${BOOTSTRAP_KUBECONFIG_SHA256%% *}"
  readonly BOOTSTRAP_KUBECONFIG BOOTSTRAP_KUBECONFIG_SHA256

  BOOTSTRAP_AGE_KEY="${BOOTSTRAP_TMP_ROOT}/age.agekey"
  BOOTSTRAP_AGE_KEY_SHA256="$(python3 "${SNAPSHOT_HELPER}" snapshot-age-key \
    "${SOPS_AGE_KEY_FILE}" "${BOOTSTRAP_AGE_KEY}")"
  readonly BOOTSTRAP_AGE_KEY BOOTSTRAP_AGE_KEY_SHA256
  derived_recipient="$(bound_age_recipient 2>"${BOOTSTRAP_TMP_ROOT}/age-keygen.log")" ||
    fail "descriptor-bound SOPS Age identity is invalid."
  [[ "${derived_recipient}" =~ ^age1[0-9a-z]{20,100}$ ]] ||
    fail "age-keygen returned an invalid recipient."
  policy_text="$(git -C "${repo}" show "${reviewed_sha}:.sops.yaml" 2>/dev/null)" ||
    fail "reviewed HEAD does not contain the SOPS creation policy."
  while IFS= read -r line; do
    if [[ "${line}" =~ ^[[:space:]]*age:[[:space:]]*(age1[0-9a-z]{20,100})[[:space:]]*$ ]]; then
      reviewed_recipients+=("${BASH_REMATCH[1]}")
    fi
  done <<<"${policy_text}"
  (( ${#reviewed_recipients[@]} == 1 )) ||
    fail "reviewed HEAD must declare exactly one local SOPS Age recipient."
  [[ "${derived_recipient}" == "${reviewed_recipients[0]}" ]] ||
    fail "SOPS Age identity does not match the recipient in reviewed HEAD."
  assert_bound_cluster_identity
}


execute_bootstrap() {
  local repo="$1" flux_dir="$2" cluster_path="$3"
  local before_sha after_sha remote_before remote_after bootstrap_log repository_url blob_manifest
  local git_dir snapshot_dir path staged_blob record_name record_blob extra
  local private_index message_file branch_ref expected_tree actual_tree changed_paths commit_message parent_record
  local index_path shared_index_snapshot reviewed_tree shared_tree final_status
  local -a generated_names generated_paths flux_args blob_ids blob_records

  require GITOPS_GITHUB_OWNER
  require GITOPS_GITHUB_REPOSITORY
  require GITOPS_GITHUB_PERSONAL
  validate_slug GITOPS_GITHUB_OWNER "${GITOPS_GITHUB_OWNER}"
  validate_slug GITOPS_GITHUB_REPOSITORY "${GITOPS_GITHUB_REPOSITORY}"
  case "${GITOPS_GITHUB_PERSONAL}" in true | false) ;; *) fail "GITOPS_GITHUB_PERSONAL must be true or false." ;; esac
  repository_url="$(flux_sync_url "${GITOPS_GITHUB_OWNER}" "${GITOPS_GITHUB_REPOSITORY}")"
  generated_names=(gotk-components.yaml gotk-sync.yaml kustomization.yaml)
  generated_paths=(
    "${cluster_path}/flux-system/gotk-components.yaml"
    "${cluster_path}/flux-system/gotk-sync.yaml"
    "${cluster_path}/flux-system/kustomization.yaml"
  )
  validate_remote_origin "${repo}" "${GITOPS_GITHUB_OWNER}" "${GITOPS_GITHUB_REPOSITORY}"
  command -v flock >/dev/null 2>&1 || fail "flock CLI not found."
  command -v kubectl >/dev/null 2>&1 || fail "kubectl CLI not found."
  command -v pnpm >/dev/null 2>&1 || fail "pnpm CLI not found."

  umask 077
  BOOTSTRAP_TMP_ROOT="$(mktemp -d)" || fail "failed to create protected bootstrap workspace."
  bootstrap_log="${BOOTSTRAP_TMP_ROOT}/bootstrap.log"
  : >"${bootstrap_log}"
  git_dir="$(git -C "${repo}" rev-parse --absolute-git-dir)" || fail "cannot resolve Git metadata directory."
  exec {BOOTSTRAP_LOCK_FD}<"${git_dir}"
  flock -x "${BOOTSTRAP_LOCK_FD}" || fail "cannot acquire the exclusive Flux bootstrap repository lock."

  validate_runtime_control_identity "${repo}" || exit 1
  assert_pristine_bootstrap_source "${repo}" "${flux_dir}"
  before_sha="$(git -C "${repo}" rev-parse --verify HEAD)"
  reviewed_tree="$(git -C "${repo}" rev-parse "${before_sha}^{tree}")"
  private_index="${BOOTSTRAP_TMP_ROOT}/index"
  GIT_INDEX_FILE="${private_index}" git -C "${repo}" read-tree "${before_sha}"
  env -u GITHUB_TOKEN -u SOPS_AGE_KEY_FILE -u KUBECONFIG \
    -u BOOTSTRAP_KUBECONFIG -u BOOTSTRAP_KUBECONFIG_SOURCE -u BOOTSTRAP_AGE_KEY \
    GIT_INDEX_FILE="${private_index}" pnpm exec lefthook run pre-commit --force \
    >"${bootstrap_log}" 2>&1 || fail "reviewed pre-commit gate rejected bootstrap source; command output was withheld."
  validate_runtime_control_identity "${repo}" || exit 1
  assert_pristine_bootstrap_source "${repo}" "${flux_dir}"
  [[ "$(git -C "${repo}" rev-parse --verify HEAD)" == "${before_sha}" ]] ||
    fail "reviewed HEAD changed while the pre-commit gate ran."
  [[ "$(GIT_INDEX_FILE="${private_index}" git -C "${repo}" write-tree)" == "${reviewed_tree}" ]] ||
    fail "reviewed pre-commit gate changed the private index."
  require GITHUB_TOKEN
  prepare_execute_snapshots "${repo}" "${before_sha}"
  flux_args=(
    bootstrap github
    --owner="${GITOPS_GITHUB_OWNER}"
    --repository="${GITOPS_GITHUB_REPOSITORY}"
    --branch="${NOHIKI_RUNTIME_CONTROL_BRANCH}"
    --path="${cluster_path}"
    --read-write-key=false
  )
  if [[ "${GITOPS_GITHUB_PERSONAL}" == true ]]; then
    flux_args+=(--personal)
  fi
  assert_cluster_flux_absent

  remote_before="$(git -C "${repo}" ls-remote --exit-code origin "refs/heads/${NOHIKI_RUNTIME_CONTROL_BRANCH}" 2>/dev/null)" ||
    fail "reviewed runtime-control branch must already exist on origin."
  [[ "${remote_before}" == "${before_sha}"$'\t'"refs/heads/${NOHIKI_RUNTIME_CONTROL_BRANCH}" ]] ||
    fail "origin runtime-control branch does not equal the reviewed local HEAD."

  snapshot_dir="${BOOTSTRAP_TMP_ROOT}/flux-output"
  generate_flux_output "${snapshot_dir}" "${cluster_path}" "${repository_url}" "${NOHIKI_RUNTIME_CONTROL_BRANCH}"
  validate_flux_output_allowlist "${snapshot_dir}" || fail "generated Flux output violated the exact allowlist."

  assert_bound_cluster_identity
  blob_manifest="$(python3 "${SNAPSHOT_HELPER}" write-flux-blobs \
    "${snapshot_dir}" "${repo}" "${flux_dir}")" ||
    fail "failed to bind validated Flux bytes to Git blobs."
  mapfile -t blob_records <<<"${blob_manifest}"
  (( ${#blob_records[@]} == ${#generated_names[@]} )) || fail "validated Flux blob manifest is incomplete."
  for i in "${!generated_names[@]}"; do
    read -r record_name record_blob extra <<<"${blob_records[$i]}"
    [[ "${record_name}" == "${generated_names[$i]}" && -z "${extra}" &&
      "${record_blob}" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] ||
      fail "validated Flux blob manifest is malformed."
    blob_ids+=("${record_blob}")
  done
  for i in "${!generated_paths[@]}"; do
    path="${generated_paths[$i]}"
    GIT_INDEX_FILE="${private_index}" git -C "${repo}" update-index \
      --add --cacheinfo "100644,${blob_ids[$i]},${path}"
    staged_blob="$(GIT_INDEX_FILE="${private_index}" git -C "${repo}" rev-parse --verify ":${path}")"
    [[ "${staged_blob}" == "${blob_ids[$i]}" ]] || fail "staged Flux blob does not equal its validated snapshot."
  done
  expected_tree="$(GIT_INDEX_FILE="${private_index}" git -C "${repo}" write-tree)" ||
    fail "cannot write the exact private-index tree."
  changed_paths="$(git -C "${repo}" diff --name-only "${before_sha}" "${expected_tree}")" ||
    fail "cannot verify the private-index tree boundary."
  [[ "${changed_paths}" == "$(printf '%s\n' "${generated_paths[@]}")" ]] ||
    fail "private-index tree contains paths outside the exact Flux allowlist."

  printf 'Flux bootstrap before Git SHA: %s\n' "${before_sha}"
  printf '%s\n' 'Flux bootstrap generated diff (content redacted):'
  GIT_INDEX_FILE="${private_index}" git -C "${repo}" diff --cached --no-ext-diff --no-color -- "${generated_paths[@]}" | redact_generated_diff

  message_file="${BOOTSTRAP_TMP_ROOT}/commit-message"
  printf '%s\n' "${FLUX_BOOTSTRAP_COMMIT_MESSAGE}" >"${message_file}"
  commit_message="$(<"${message_file}")"
  [[ "${commit_message}" == "${FLUX_BOOTSTRAP_COMMIT_MESSAGE}" ]] ||
    fail "Flux bootstrap commit message changed unexpectedly."
  actual_tree="$(GIT_INDEX_FILE="${private_index}" git -C "${repo}" write-tree)" ||
    fail "cannot verify the private-index tree."
  [[ "${actual_tree}" == "${expected_tree}" ]] || fail "private index changed before commit creation."

  after_sha="$(git -C "${repo}" commit-tree "${expected_tree}" -p "${before_sha}" -F "${message_file}")" ||
    fail "failed to create the reviewed Flux bootstrap commit."
  [[ "$(git -C "${repo}" rev-parse "${after_sha}^{tree}")" == "${expected_tree}" ]] ||
    fail "Flux bootstrap commit tree does not equal the reviewed private-index tree."
  parent_record="$(git -C "${repo}" rev-list --parents -n 1 "${after_sha}")"
  [[ "${parent_record}" == "${after_sha} ${before_sha}" ]] ||
    fail "Flux bootstrap commit does not have the exact reviewed parent."
  [[ "$(git -C "${repo}" log -1 --format=%B "${after_sha}")" == "${FLUX_BOOTSTRAP_COMMIT_MESSAGE}" ]] ||
    fail "Flux bootstrap commit message does not equal the reviewed message."
  branch_ref="refs/heads/${NOHIKI_RUNTIME_CONTROL_BRANCH}"
  index_path="${git_dir}/index"
  BOOTSTRAP_GIT_INDEX_LOCK="${git_dir}/index.lock"
  (set -o noclobber; : >"${BOOTSTRAP_GIT_INDEX_LOCK}") 2>/dev/null ||
    fail "cannot acquire the Git index lock for final Flux materialization."
  shared_index_snapshot="${BOOTSTRAP_TMP_ROOT}/shared-index"
  cp -- "${index_path}" "${shared_index_snapshot}"
  shared_tree="$(GIT_INDEX_FILE="${shared_index_snapshot}" git -C "${repo}" write-tree)" ||
    fail "cannot verify the locked shared Git index."
  [[ "${shared_tree}" == "${reviewed_tree}" ]] ||
    fail "shared Git index changed after bootstrap review; refusing branch mutation."
  cp -- "${shared_index_snapshot}" "${BOOTSTRAP_GIT_INDEX_LOCK}"
  for i in "${!generated_paths[@]}"; do
    GIT_INDEX_FILE="${BOOTSTRAP_GIT_INDEX_LOCK}" git -C "${repo}" update-index \
      --add --cacheinfo "100644,${blob_ids[$i]},${generated_paths[$i]}"
  done
  [[ "$(GIT_INDEX_FILE="${BOOTSTRAP_GIT_INDEX_LOCK}" git -C "${repo}" write-tree)" == "${expected_tree}" ]] ||
    fail "locked shared index does not equal the validated Flux tree."
  GIT_INDEX_FILE="${BOOTSTRAP_GIT_INDEX_LOCK}" git -C "${repo}" diff --quiet "${expected_tree}" -- ||
    fail "worktree does not equal the validated Flux tree."
  mv -f -- "${BOOTSTRAP_GIT_INDEX_LOCK}" "${index_path}"
  BOOTSTRAP_GIT_INDEX_LOCK=""
  assert_bound_cluster_identity
  git -C "${repo}" update-ref "${branch_ref}" "${after_sha}" "${before_sha}" ||
    fail "runtime-control branch changed concurrently; refusing to publish the Flux commit."
  final_status="$(git -C "${repo}" status --porcelain=v1 --untracked-files=all)"
  [[ -z "${final_status}" ]] || fail "successful Flux bootstrap commit did not leave a pristine worktree."
  printf 'Flux bootstrap after Git SHA: %s\n' "${after_sha}"

  assert_bound_cluster_identity
  git -C "${repo}" push origin "${after_sha}:${branch_ref}" >"${bootstrap_log}" 2>&1 ||
    fail "failed to push the immutable runtime-control bootstrap commit; command output was withheld to protect credentials."

  remote_after="$(git -C "${repo}" ls-remote --exit-code origin "refs/heads/${NOHIKI_RUNTIME_CONTROL_BRANCH}" 2>/dev/null)" ||
    fail "cannot verify the runtime-control branch after bootstrap push."
  [[ "${remote_after}" == "${after_sha}"$'\t'"refs/heads/${NOHIKI_RUNTIME_CONTROL_BRANCH}" ]] ||
    fail "pushed runtime-control branch does not equal the reviewed Flux bootstrap commit."

  assert_bound_cluster_identity
  bound_kubectl create namespace "${GITOPS_NAMESPACE}" --dry-run=client -o yaml |
    bound_kubectl apply -f - >/dev/null

  assert_bound_cluster_identity
  bound_kubectl_with_age create secret generic sops-age -n "${GITOPS_NAMESPACE}" \
    --from-file=age.agekey=@AGEKEY@ --dry-run=client -o yaml |
    bound_kubectl apply -f - >/dev/null

  assert_bound_cluster_identity
  bound_flux "${flux_args[@]}" >"${bootstrap_log}" 2>&1 ||
    fail "Flux cluster bootstrap failed; command output was withheld to protect credentials."

  remote_after="$(git -C "${repo}" ls-remote --exit-code origin "refs/heads/${NOHIKI_RUNTIME_CONTROL_BRANCH}" 2>/dev/null)" ||
    fail "cannot verify the runtime-control branch after bootstrap."
  [[ "${remote_after}" == "${after_sha}"$'\t'"refs/heads/${NOHIKI_RUNTIME_CONTROL_BRANCH}" ]] ||
    fail "Flux attempted an unreviewed Git write outside the pre-generated commit."
  printf '%s\n' 'Flux one-time bootstrap completed; use normal reconcile for all subsequent convergence.'
}

main() {
  local mode script_dir repo cluster_path flux_dir dry_run_dir repository_url
  mode="$(parse_mode "$@")" || exit $?
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=runtime-control-policy.sh
  source "${script_dir}/runtime-control-policy.sh"
  SNAPSHOT_HELPER="${script_dir}/secure-snapshot.py"
  readonly SNAPSHOT_HELPER
  [[ -f "${SNAPSHOT_HELPER}" && ! -L "${SNAPSHOT_HELPER}" ]] || fail "secure snapshot helper is absent or unsafe."
  repo="$(git -C "${script_dir}" rev-parse --show-toplevel 2>/dev/null)" || fail "bootstrap must run inside a Git worktree."
  trap cleanup_bootstrap EXIT

  require NOHIKI_CLUSTER
  [[ "${NOHIKI_CLUSTER}" == "local" ]] ||
    fail "this bounded bootstrap supports only NOHIKI_CLUSTER=local; non-local bootstrap requires a separately reviewed authority path."
  validate_runtime_control_identity "${repo}" || exit 1
  export GITOPS_GITHUB_BRANCH="${NOHIKI_RUNTIME_CONTROL_BRANCH}"
  cluster_path="infra/k8s/gitops/clusters/local"
  flux_dir="${repo}/${cluster_path}/flux-system"
  [[ -d "${repo}/${cluster_path}" ]] || fail "local cluster source directory is absent."
  assert_pristine_bootstrap_source "${repo}" "${flux_dir}"

  case "${mode}" in
    --validate)
      printf '%s\n' 'bootstrap validation: runtime-control identity and pristine Flux state accepted'
      ;;
    --dry-run)
      require GITOPS_GITHUB_OWNER
      require GITOPS_GITHUB_REPOSITORY
      validate_slug GITOPS_GITHUB_OWNER "${GITOPS_GITHUB_OWNER}"
      validate_slug GITOPS_GITHUB_REPOSITORY "${GITOPS_GITHUB_REPOSITORY}"
      command -v flux >/dev/null 2>&1 || fail "flux CLI not found."
      umask 077
      BOOTSTRAP_TMP_ROOT="$(mktemp -d)" || fail "failed to create a temporary Flux render directory."
      dry_run_dir="${BOOTSTRAP_TMP_ROOT}/flux-output"
      repository_url="$(flux_sync_url "${GITOPS_GITHUB_OWNER}" "${GITOPS_GITHUB_REPOSITORY}")"
      generate_flux_output "${dry_run_dir}" "${cluster_path}" "${repository_url}" "${NOHIKI_RUNTIME_CONTROL_BRANCH}"
      python3 "${SNAPSHOT_HELPER}" validate-flux "${dry_run_dir}"
      validate_flux_output_allowlist "${dry_run_dir}" || exit 1
      assert_pristine_bootstrap_source "${repo}" "${flux_dir}"
      printf '%s\n' 'bootstrap dry-run: exact Flux output allowlist accepted; no Git or Kubernetes writes performed'
      ;;
    --execute)
      command -v flux >/dev/null 2>&1 || fail "flux CLI not found."
      execute_bootstrap "${repo}" "${flux_dir}" "${cluster_path}"
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
