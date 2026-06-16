#!/usr/bin/env bash
set -euo pipefail

NS="data-pipeline"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up periodic_failure_window scenario resources..."
oc delete deployment batch-processor -n "$NS" --ignore-not-found --grace-period=0
oc delete secret batch-processor-logs-script -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra.sh
source "$SCRIPT_DIR/../_common/cleanup_infra.sh"
echo "Cleanup complete."
