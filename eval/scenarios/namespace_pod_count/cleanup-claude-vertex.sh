#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"

echo "Cleaning up namespace_pod_count scenario resources..."
oc delete -f "$FIXTURE_DIR/manifests.yaml" --ignore-not-found
oc delete namespace fleet-alpha fleet-alpha1 --ignore-not-found

# shellcheck source=../_common/cleanup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/cleanup_infra-claude-vertex.sh"
echo "Cleanup complete."
