#!/usr/bin/env bash
set -euo pipefail

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
NAMESPACE="bookinfo"
WAIT_SECONDS=${WAIT_SECONDS:-180}  # override with: make all WAIT_SECONDS=60
KUBECTL="${KUBECTL:-oc}"

# ── Apply the latency fault injection manifests ───────────────────────────────
echo "Applying invalid Istio object manifests…"
$KUBECTL apply -f "$FIXTURE_DIR/manifests.yaml"

# Verify the Istio object was created
ATTEMPT=0
VS=0
until [ "$ATTEMPT" -ge 10 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  VS=$($KUBECTL get virtualservice reviews-bad-config -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
  if [ "$VS" -ge 1 ]; then
    echo "VirtualService reviews-bad-config is active in namespace $NAMESPACE"
    break
  fi
  echo "attempt $ATTEMPT/10 — reviews-bad-config not yet visible, waiting 3s…"
  sleep 3
done

if [ "$VS" -lt 1 ]; then
  echo "ERROR: VirtualService reviews-bad-config was not created in namespace $NAMESPACE"
  exit 1
fi

echo "Waiting ${WAIT_SECONDS}s for Istio to process the invalid object…"
sleep "$WAIT_SECONDS"
echo "Setup complete — invalid Istio object is active in namespace $NAMESPACE."
