#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="cache-tier"
PVC="memcached-data-pvc"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra.sh
source "$SCRIPT_DIR/../_common/setup_infra.sh"

# Deploy the broken workload
oc apply -f "$FIXTURE_DIR/manifest.yaml"

echo "Waiting for ProvisioningFailed event on PVC..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 60 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  STATUS=$(oc get events -n "$NS" \
    --field-selector "involvedObject.name=$PVC,involvedObject.kind=PersistentVolumeClaim" \
    -o jsonpath='{.items[*].reason}' 2>/dev/null || true)
  if echo "$STATUS" | grep -q "ProvisioningFailed"; then
    echo "ProvisioningFailed event detected (attempt $ATTEMPT)."
    echo "Setup complete."
    exit 0
  fi
  sleep 1
done

echo "ERROR: ProvisioningFailed event not detected within timeout." >&2
oc describe pvc "$PVC" -n "$NS"
exit 1
