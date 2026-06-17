#!/usr/bin/env bash
set -euo pipefail

NS="warehouse-ops"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up envvar_missing scenario resources..."
oc delete deployment order-fulfillment-daemon -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/cleanup_infra-claude-vertex.sh"
echo "Cleanup complete."
