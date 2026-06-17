#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="ingress-layer"
APP="gateway-proxy"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/setup_infra-claude-vertex.sh"

# Deploy the workload
oc create namespace "$NS" 2>/dev/null || true

oc create secret generic gateway-proxy-log-script \
  --from-file=generate_logs.py="$FIXTURE_DIR/generate_logs.py" \
  -n "$NS" --dry-run=client -o yaml | oc apply -f -
oc apply -f "$FIXTURE_DIR/manifest.yaml"

echo "Waiting for log sentinels..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 40 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  if oc wait --for=condition=ready pod -l "app=$APP" -n "$NS" --timeout=2s 2>/dev/null; then
    LOGS=$(oc logs -l "app=$APP" -n "$NS" --tail=10000 2>/dev/null || true)
    if echo "$LOGS" | grep -q "Configuration file change detected" \
    && echo "$LOGS" | grep -q '500 GET /api/health - Connection refused'; then
      echo "Log sentinels found after $ATTEMPT checks."
      echo "Setup complete."
      exit 0
    fi
  fi
  echo "check $ATTEMPT/40 — waiting 3s..."
  sleep 3
done

echo "ERROR: Sentinels not found within timeout." >&2
oc logs -l "app=$APP" -n "$NS" --tail=30 2>/dev/null || true
exit 1
