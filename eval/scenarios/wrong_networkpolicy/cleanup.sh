#!/usr/bin/env bash
set -euo pipefail

NS="service-mesh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up wrong_networkpolicy scenario resources..."
oc delete deployment frontend -n "$NS" --ignore-not-found
oc delete deployment backend -n "$NS" --ignore-not-found
oc delete svc backend-service -n "$NS" --ignore-not-found
oc delete networkpolicy backend-network-policy -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra.sh
source "$SCRIPT_DIR/../_common/cleanup_infra.sh"
echo "Cleanup complete."
