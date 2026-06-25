#!/usr/bin/env bash
set -euo pipefail

# Deploy OpenAI provider infrastructure for the payments alert-storm scenario.
# Assumes the payments workload is already deployed in the target namespaces.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_setup_infra-openai.sh
source "$SCRIPT_DIR/_setup_infra-openai.sh"

echo "Verifying payments workload is present..."
oc get namespace payments >/dev/null
oc get namespace shared-services >/dev/null
echo "Setup complete."
