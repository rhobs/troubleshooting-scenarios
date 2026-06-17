#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="catalog-mgmt"
JOB="inventory-sync-validator"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/setup_infra-claude-vertex.sh"

# Deploy the broken workload
oc create namespace "$NS" 2>/dev/null || true

oc create secret generic inventory-sync-logs-script \
  --from-file=generate_logs.py="$FIXTURE_DIR/generate_logs.py" \
  -n "$NS" --dry-run=client -o yaml | oc apply -f -
oc apply -f "$FIXTURE_DIR/job.yaml"

echo "Waiting for job logs to contain expected sentinels..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 20 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  LOGS=$(oc logs -l "job-name=$JOB" -n "$NS" --tail=100 2>/dev/null || true)
  if echo "$LOGS" | grep -q "Target host: prod-db, port: 3333" \
  && echo "$LOGS" | grep -q "FATAL: Unable to connect to required database"; then
    echo "Both sentinels found (attempt $ATTEMPT)."
    echo "Setup complete."
    exit 0
  fi
  sleep 3
done

echo "ERROR: Sentinels not found within timeout." >&2
oc logs -l "job-name=$JOB" -n "$NS" --tail=30 2>/dev/null || true
exit 1
