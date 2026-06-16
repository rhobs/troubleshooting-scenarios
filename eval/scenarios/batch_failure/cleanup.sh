#!/usr/bin/env bash
set -euo pipefail

NS="catalog-mgmt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up batch_failure scenario resources..."
oc delete job inventory-sync-validator -n "$NS" --ignore-not-found
oc delete secret inventory-sync-logs-script -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra.sh
source "$SCRIPT_DIR/../_common/cleanup_infra.sh"
echo "Cleanup complete."
