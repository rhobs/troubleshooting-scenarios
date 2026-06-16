#!/usr/bin/env bash
set -euo pipefail

NS="cache-tier"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up storage_binding scenario resources..."
oc delete pvc memcached-data-pvc -n "$NS" --ignore-not-found
oc delete deployment memcached -n "$NS" --ignore-not-found
oc delete svc memcached -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra.sh
source "$SCRIPT_DIR/../_common/cleanup_infra.sh"
echo "Cleanup complete."
