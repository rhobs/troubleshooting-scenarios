#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="warehouse-ops"
APP="order-fulfillment-daemon"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra.sh
source "$SCRIPT_DIR/../_common/setup_infra.sh"

# Deploy the broken workload
oc apply -f "$FIXTURE_DIR/deployment.yaml"

echo "Waiting for $APP pod to be created..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 60 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  POD=$(oc get pods -n "$NS" -l "app=$APP" -o name 2>/dev/null | head -1)
  [ -n "$POD" ] && break
  sleep 5
done
[ -n "${POD:-}" ] || { echo "$APP pod never appeared"; oc get pods -n "$NS"; exit 1; }

echo "Pod exists — waiting for CrashLoopBackOff..."
oc wait --for=jsonpath='{.status.containerStatuses[0].state.waiting.reason}'=CrashLoopBackOff \
  pod -l "app=$APP" -n "$NS" --timeout=300s

echo "Setup complete."
