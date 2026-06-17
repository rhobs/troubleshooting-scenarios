#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_DIR="$SCRIPT_DIR/fixtures"
NS="service-mesh"

# Deploy agentic infrastructure (LLMProvider, Agent CRDs)
# shellcheck source=../_common/setup_infra-claude-vertex.sh
source "$SCRIPT_DIR/../_common/setup_infra-claude-vertex.sh"

# Deploy backend + frontend + broken NetworkPolicy
oc apply -f "$FIXTURE_DIR/manifest.yaml"
oc wait --for=condition=available deployment/backend -n "$NS" --timeout=60s

echo "Waiting for connection timeout error in frontend logs..."
ATTEMPT=0
until [ "$ATTEMPT" -ge 30 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  if oc logs -l app=frontend -n "$NS" --tail=20 2>/dev/null \
     | grep -q "ERROR: Connection timeout to backend-service!"; then
    echo "Timeout error detected (attempt $ATTEMPT)."
    echo "Setup complete."
    exit 0
  fi
  echo "attempt $ATTEMPT/30 — waiting 3s..."
  sleep 3
done

echo "ERROR: Connection timeout error not found within 90s." >&2
oc get pods -n "$NS"
oc logs -l app=frontend -n "$NS" --tail=10 2>/dev/null || true
exit 1
