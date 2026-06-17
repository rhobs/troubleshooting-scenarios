#!/usr/bin/env bash
set -euo pipefail

NS="ingress-layer"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up config_drift_analysis scenario resources..."
oc delete deployment gateway-proxy -n "$NS" --ignore-not-found --wait=false
oc delete secret gateway-proxy-log-script -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/cleanup_infra-claude-vertex.sh"
echo "Cleanup complete."
