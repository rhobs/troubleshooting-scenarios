#!/usr/bin/env bash
set -euo pipefail

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
NAMESPACE="bookinfo"
WAIT_SECONDS=${WAIT_SECONDS:-180}  # override with: make all WAIT_SECONDS=60
KUBECTL="${KUBECTL:-oc}"

echo "Removing invalid Istio object manifests…"
$KUBECTL delete -f "$FIXTURE_DIR/manifests.yaml" --ignore-not-found

echo "Waiting ${WAIT_SECONDS}s for Istio to process the invalid object removal…"
sleep "$WAIT_SECONDS"
echo "Cleanup complete — invalid Istio object removed from namespace $NAMESPACE."
