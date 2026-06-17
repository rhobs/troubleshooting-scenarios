#!/usr/bin/env bash
set -euo pipefail

NS="analytics-platform"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up scheduled_outage_detection scenario resources..."
oc delete statefulset report-generator -n "$NS" --ignore-not-found --wait=false
oc delete secret report-generator-logs-script -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/cleanup_infra-claude-vertex.sh"
echo "Cleanup complete."
