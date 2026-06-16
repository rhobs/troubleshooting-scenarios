#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="analytics-platform"
APP="report-generator"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra.sh
source "$SCRIPT_DIR/../_common/setup_infra.sh"

# Deploy the workload
oc create namespace "$NS" 2>/dev/null || true

oc create secret generic report-generator-logs-script \
  --from-file=generate_logs.py="$FIXTURE_DIR/generate_logs.py" \
  -n "$NS" --dry-run=client -o yaml | oc apply -f -
oc apply -f "$FIXTURE_DIR/manifest.yaml"

logs_ready() {
  local logs
  logs=$(oc logs -l "app=$APP" -n "$NS" --tail=10000 2>/dev/null || true)
  echo "$logs" | grep "Detected repeated failures during 03:00-03:05 window" >/dev/null || return 1
  echo "$logs" | grep "System health check passed" >/dev/null || return 1
  echo "$logs" | grep "Job executed successfully in 167ms\." >/dev/null || return 1
}

echo "Waiting for log sentinels..."
ATTEMPT=0
until logs_ready; do
  ATTEMPT=$((ATTEMPT + 1))
  [ "$ATTEMPT" -lt 40 ] || { echo "ERROR: Sentinels not found after 40 checks." >&2; oc get pods -n "$NS"; exit 1; }
  echo "check $ATTEMPT/40 — waiting 3s..."
  sleep 3
done
echo "All log sentinels present (attempt $ATTEMPT)."
echo "Setup complete."
