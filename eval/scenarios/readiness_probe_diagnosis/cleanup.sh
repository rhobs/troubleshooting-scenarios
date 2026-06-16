#!/usr/bin/env bash
set -euo pipefail

NS="discovery-hub"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up readiness_probe_diagnosis scenario resources..."
oc delete pod catalog-index-service -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra.sh
source "$SCRIPT_DIR/../_common/cleanup_infra.sh"
echo "Cleanup complete."
