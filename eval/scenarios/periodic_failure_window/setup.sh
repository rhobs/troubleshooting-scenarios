#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="data-pipeline"
APP="batch-processor"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra.sh
source "$SCRIPT_DIR/../_common/setup_infra.sh"

# Deploy the workload
oc create namespace "$NS" 2>/dev/null || true

oc create secret generic batch-processor-logs-script \
  --from-file=generate_logs.py="$FIXTURE_DIR/generate_logs.py" \
  -n "$NS" --dry-run=client -o yaml | oc apply -f -
oc apply -f "$FIXTURE_DIR/manifest.yaml"

SENTINELS=(
  "Detected repeated failures during 03:00-03:05 window"
  "System health check passed"
  "Job executed successfully in 167ms."
)

echo "Waiting for log sentinels..."
ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT + 1))
  [ "$ATTEMPT" -le 50 ] || { echo "ERROR: Sentinels not found after 50 checks." >&2; oc get pods -n "$NS"; exit 1; }

  LOGS=$(oc logs -l "app=$APP" -n "$NS" --tail=10000 2>/dev/null || true)
  ALL_FOUND=true
  for s in "${SENTINELS[@]}"; do
    echo "$LOGS" | grep -F "$s" >/dev/null || { ALL_FOUND=false; break; }
  done

  if $ALL_FOUND; then
    echo "All sentinels found (attempt $ATTEMPT)."
    echo "Setup complete."
    exit 0
  fi
  echo "check $ATTEMPT/50 — waiting 3s..."
  sleep 3
done
