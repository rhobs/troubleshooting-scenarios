#!/usr/bin/env bash
set -euo pipefail

# Deploy Claude/Vertex AI provider infrastructure for the payments alert-storm scenario.
# Assumes the payments workload is already deployed in the target namespaces.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_setup_infra-claude-vertex.sh
source "$SCRIPT_DIR/_setup_infra-claude-vertex.sh"

echo "Verifying payments workload is present..."
oc get namespace payments >/dev/null
oc get namespace shared-services >/dev/null
echo "Setup complete."
