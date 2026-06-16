#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="oom-scenario"
APP="awesome-application"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra.sh
source "$SCRIPT_DIR/../_common/setup_infra.sh"

# Deploy the broken workload
oc apply -f "$FIXTURE_DIR/manifest.yaml"

echo "Waiting for $APP to be OOMKilled..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 90 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  STATUSES=$(oc get pods -n "$NS" -l "app=$APP" \
    -o jsonpath='{range .items[*]}{.status.containerStatuses[0].lastState.terminated.reason}{"\n"}{end}' 2>/dev/null || true)
  if echo "$STATUSES" | grep -q "OOMKilled"; then
    echo "OOMKilled detected (attempt $ATTEMPT)."
    echo "Setup complete."
    exit 0
  fi
  sleep 2
done

echo "ERROR: OOMKilled not detected within timeout." >&2
oc get pods -n "$NS" -l "app=$APP"
exit 1
