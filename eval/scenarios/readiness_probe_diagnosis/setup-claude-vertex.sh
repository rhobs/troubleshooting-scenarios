#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="discovery-hub"
POD_NAME="catalog-index-service"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/setup_infra-claude-vertex.sh"

# Deploy the broken workload
oc apply -f "$FIXTURE_DIR/manifest.yaml"

echo "Waiting for Readiness probe failure event..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 60 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  EVENTS=$(oc get events -n "$NS" \
    --field-selector "involvedObject.name=$POD_NAME,reason=Unhealthy" \
    -o jsonpath='{.items[*].message}' 2>/dev/null || true)
  if echo "$EVENTS" | grep -q "Readiness probe failed"; then
    echo "Readiness probe failure event found (attempt $ATTEMPT)."
    echo "Setup complete."
    exit 0
  fi
  sleep 1
done

echo "ERROR: Readiness probe failure not detected within timeout." >&2
oc describe pod "$POD_NAME" -n "$NS"
exit 1
