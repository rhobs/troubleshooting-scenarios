#!/usr/bin/env bash
set -euo pipefail

# Tear down OpenAI provider infrastructure for the payments alert-storm scenario.

export OPERATOR_NS="openshift-lightspeed"
export TEST_NS="lightspeed-evaluation-test"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up payments integration test resources..."

# shellcheck source=_cleanup_infra-openai.sh
source "$SCRIPT_DIR/_cleanup_infra-openai.sh"
echo "Cleanup complete."
