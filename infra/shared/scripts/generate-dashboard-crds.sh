#!/usr/bin/env bash
# =============================================================================
# Generate GrafanaDashboard CRDs from shared dashboard JSON files.
#
# Source: infra/shared/dashboards/*.json
# Target: infra/k8s/observability/base/grafana/dashboards/*.yaml
#
# Run via: just generate-dashboard-crds
# =============================================================================
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
DASHBOARDS_SRC="$REPO_ROOT/infra/shared/dashboards"
DASHBOARDS_DST="$REPO_ROOT/infra/k8s/observability/base/grafana/dashboards"

if [[ ! -d "$DASHBOARDS_SRC" ]]; then
  echo "ERROR: Dashboard source directory not found: $DASHBOARDS_SRC"
  exit 1
fi

mkdir -p "$DASHBOARDS_DST"
tmp_file=""
cleanup() {
  [[ -z "$tmp_file" ]] || rm -f -- "$tmp_file"
}
trap cleanup EXIT

count=0
for json_file in "$DASHBOARDS_SRC"/*.json; do
  [[ -f "$json_file" ]] || continue

  filename=$(basename "$json_file" .json)
  yaml_file="$DASHBOARDS_DST/$filename.yaml"
  if [[ ! "$filename" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || (( ${#filename} > 63 )); then
    echo "ERROR: Dashboard filename is not a valid Kubernetes name: $filename" >&2
    exit 1
  fi


  # Parse through argv rather than interpolating paths into Python source. Invalid
  # dashboards must stop generation instead of producing a broken CRD.
  metadata=$(python3 - "$json_file" "$filename" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    dashboard = json.load(source)

uid = dashboard.get("uid", sys.argv[2])
title = dashboard.get("title", sys.argv[2])
if not isinstance(uid, str) or not uid:
    raise ValueError("dashboard uid must be a non-empty string")
if not isinstance(title, str) or not title:
    raise ValueError("dashboard title must be a non-empty string")
print(f"uid={uid}, title={title}")
PY
)

  tmp_file=$(mktemp "$DASHBOARDS_DST/.${filename}.yaml.XXXXXXXX")
  cat > "$tmp_file" <<YAML
# Auto-generated from infra/shared/dashboards/${filename}.json
# Do not edit manually - re-run: just generate-dashboard-crds
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: ${filename}
spec:
  instanceSelector:
    matchLabels:
      dashboards: nohiki
  folder: "Nohiki"
  json: |
$(sed 's/^/    /' "$json_file")
YAML
  mv -- "$tmp_file" "$yaml_file"
  tmp_file=""

  count=$((count + 1))
  echo "  Generated: $yaml_file ($metadata)"
done

echo ""
echo "Generated $count dashboard CRD(s) in $DASHBOARDS_DST"
