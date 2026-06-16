#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS_A="fleet-alpha"
NS_B="fleet-alpha1"
EXPECTED_A=6
EXPECTED_B=9

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra.sh
source "$SCRIPT_DIR/../_common/setup_infra.sh"

# Deploy the workloads
oc apply -f "$FIXTURE_DIR/manifests.yaml"

echo "Waiting for all pods to reach Running..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 20 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  COUNT_A=$(oc get pods -n "$NS_A" --no-headers --field-selector=status.phase=Running 2>/dev/null | wc -l | tr -d ' ')
  COUNT_B=$(oc get pods -n "$NS_B" --no-headers --field-selector=status.phase=Running 2>/dev/null | wc -l | tr -d ' ')

  if [ "$COUNT_A" -eq "$EXPECTED_A" ] && [ "$COUNT_B" -eq "$EXPECTED_B" ]; then
    echo "Pod counts OK — $NS_A:$COUNT_A  $NS_B:$COUNT_B"
    echo "Setup complete."
    exit 0
  fi
  echo "attempt $ATTEMPT/20 — $NS_A:$COUNT_A/$EXPECTED_A  $NS_B:$COUNT_B/$EXPECTED_B — waiting 3s..."
  sleep 3
done

echo "ERROR: Expected pod counts not reached." >&2
oc get pods -n "$NS_A"
oc get pods -n "$NS_B"
exit 1
