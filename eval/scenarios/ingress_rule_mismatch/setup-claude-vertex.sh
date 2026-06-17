#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="platform-core"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/setup_infra-claude-vertex.sh"

# Deploy api-gateway (backend + netpol) and wait for it
oc apply -f "$FIXTURE_DIR/api-gateway.yaml"
oc wait --for=condition=available deployment/api-gateway -n "$NS" --timeout=60s

# Deploy the web-portal (frontend) that will be blocked by the NetworkPolicy
oc apply -f "$FIXTURE_DIR/web-portal.yaml"

echo "Waiting for connection timeout error in web-portal logs..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 30 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  if oc logs -l app=web-portal -n "$NS" --tail=20 2>/dev/null \
     | grep -q "ERROR: Connection timeout to api-gateway-svc!"; then
    echo "Timeout error detected (attempt $ATTEMPT)."
    echo "Setup complete."
    exit 0
  fi
  echo "attempt $ATTEMPT/30 — waiting 2s..."
  sleep 2
done

echo "ERROR: Connection timeout error not found within 60s." >&2
oc get pods -n "$NS"
oc logs -l app=web-portal -n "$NS" --tail=10 2>/dev/null || true
exit 1
