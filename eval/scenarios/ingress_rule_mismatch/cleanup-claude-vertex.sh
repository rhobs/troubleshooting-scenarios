#!/usr/bin/env bash
set -euo pipefail

NS="platform-core"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up ingress_rule_mismatch scenario resources..."
oc delete deployment web-portal -n "$NS" --ignore-not-found
oc delete deployment api-gateway -n "$NS" --ignore-not-found
oc delete svc api-gateway-svc -n "$NS" --ignore-not-found
oc delete networkpolicy restrict-api-gateway-ingress -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/cleanup_infra-claude-vertex.sh"
echo "Cleanup complete."
