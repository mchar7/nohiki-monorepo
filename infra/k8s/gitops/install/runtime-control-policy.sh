#!/usr/bin/env bash
# Sourceable, read-only policy seams for the one-time Flux bootstrap.

runtime_control_policy_error() {
  printf 'Error: %s\n' "$*" >&2
  return 1
}

require_policy_value() {
  local name="$1"
  [[ -n "${!name:-}" ]] || runtime_control_policy_error "${name} is required (fail-closed)."
}

validate_runtime_control_identity() {
  local repo="${1:-.}"
  local branch head

  require_policy_value NOHIKI_RUNTIME_CONTROL_BRANCH || return
  require_policy_value NOHIKI_REVIEWED_TOPIC_SHA || return

  [[ "${NOHIKI_RUNTIME_CONTROL_BRANCH}" =~ ^runtime-control/local/[a-z0-9][a-z0-9._-]*$ ]] ||
    runtime_control_policy_error \
      "NOHIKI_RUNTIME_CONTROL_BRANCH must match ^runtime-control/local/[a-z0-9][a-z0-9._-]*$." || return
  [[ "${NOHIKI_REVIEWED_TOPIC_SHA}" =~ ^[0-9a-f]{40}$ ]] ||
    runtime_control_policy_error "NOHIKI_REVIEWED_TOPIC_SHA must be a lowercase full 40-hex Git SHA." || return

  branch="$(git -C "${repo}" symbolic-ref --quiet --short HEAD 2>/dev/null)" ||
    runtime_control_policy_error "detached HEAD is forbidden for Flux bootstrap." || return
  [[ "${branch}" == "${NOHIKI_RUNTIME_CONTROL_BRANCH}" ]] ||
    runtime_control_policy_error \
      "current branch must exactly equal NOHIKI_RUNTIME_CONTROL_BRANCH." || return

  case "${branch}" in
    main | integration/* | refs/pull/*)
      runtime_control_policy_error "protected, integration, and pull-request refs are forbidden for Flux bootstrap."
      return
      ;;
  esac

  head="$(git -C "${repo}" rev-parse --verify HEAD 2>/dev/null)" ||
    runtime_control_policy_error "cannot resolve the current Git HEAD." || return
  [[ "${head}" == "${NOHIKI_REVIEWED_TOPIC_SHA}" ]] ||
    runtime_control_policy_error "current HEAD does not equal NOHIKI_REVIEWED_TOPIC_SHA." || return

  if [[ -n "${GITOPS_GITHUB_BRANCH:-}" && "${GITOPS_GITHUB_BRANCH}" != "${branch}" ]]; then
    runtime_control_policy_error "GITOPS_GITHUB_BRANCH must equal the reviewed runtime-control branch."
    return
  fi
  if [[ -n "${GITHUB_REF:-}" && "${GITHUB_REF}" != "refs/heads/${branch}" ]]; then
    runtime_control_policy_error "GITHUB_REF must identify the reviewed runtime-control branch; PR refs are forbidden."
    return
  fi
  if [[ -n "${GITHUB_REF_NAME:-}" && "${GITHUB_REF_NAME}" != "${branch}" ]]; then
    runtime_control_policy_error "GITHUB_REF_NAME does not match the reviewed runtime-control branch."
    return
  fi
  if [[ -n "${GITHUB_HEAD_REF:-}" && "${GITHUB_HEAD_REF}" != "${branch}" ]]; then
    runtime_control_policy_error "GITHUB_HEAD_REF does not match the reviewed runtime-control branch."
    return
  fi
  if [[ -n "${GITHUB_SHA:-}" && "${GITHUB_SHA}" != "${head}" ]]; then
    runtime_control_policy_error "GITHUB_SHA does not match the reviewed Git HEAD."
    return
  fi
}

_flux_directory_entries() {
  local directory="$1"
  local restore_nullglob restore_dotglob
  restore_nullglob="$(shopt -p nullglob || true)"
  restore_dotglob="$(shopt -p dotglob || true)"
  shopt -s nullglob dotglob
  FLUX_STATE_ENTRIES=("${directory}"/*)
  eval "${restore_nullglob}"
  eval "${restore_dotglob}"
}

classify_flux_state() {
  local directory="$1"
  local entry name
  local -a expected=(gotk-components.yaml gotk-sync.yaml kustomization.yaml)
  local -a names=()

  if [[ ! -e "${directory}" ]]; then
    printf 'absent\n'
    return
  fi
  [[ -d "${directory}" && ! -L "${directory}" ]] ||
    runtime_control_policy_error "Flux state path must be a real directory." || return

  _flux_directory_entries "${directory}"
  if (( ${#FLUX_STATE_ENTRIES[@]} == 0 )); then
    printf 'absent\n'
    return
  fi

  for entry in "${FLUX_STATE_ENTRIES[@]}"; do
    [[ -f "${entry}" && ! -L "${entry}" ]] ||
      runtime_control_policy_error "unknown non-regular entry exists in flux-system state." || return
    name="${entry##*/}"
    case "${name}" in
      gotk-components.yaml | gotk-sync.yaml | kustomization.yaml) names+=("${name}") ;;
      *) runtime_control_policy_error "unknown file exists in flux-system state: ${name}"; return ;;
    esac
  done

  (( ${#names[@]} == ${#expected[@]} )) ||
    runtime_control_policy_error "partial flux-system state is forbidden; all three generated files must be present." || return
  printf 'complete\n'
}

validate_flux_output_allowlist() {
  local state
  state="$(classify_flux_state "$1")" || return
  [[ "${state}" == "complete" ]] ||
    runtime_control_policy_error "generated Flux output is incomplete." || return
}

redact_generated_diff() {
  local line
  while IFS= read -r line; do
    case "${line}" in
      'diff --git '* | 'index '* | '--- '* | '+++ '* | '@@ '*) printf '%s\n' "${line}" ;;
      +* | -*) printf '%s\n' "${line:0:1}<redacted generated line>" ;;
      *) printf '%s\n' '<redacted context line>' ;;
    esac
  done
}
