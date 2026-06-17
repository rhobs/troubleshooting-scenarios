#!/usr/bin/env bash
set -euo pipefail

NS="oom-scenario"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up OOM scenario resources..."
oc delete deployment awesome-application -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

# shellcheck source=../_common/cleanup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/cleanup_infra-claude-vertex.sh"
echo "Cleanup complete."
