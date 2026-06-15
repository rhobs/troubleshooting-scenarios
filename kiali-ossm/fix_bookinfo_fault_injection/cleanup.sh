#!/usr/bin/env bash
KUBECTL=${KUBECTL:-oc}   # kubectl for kind, oc for OpenShift (set via CLUSTER env)
set -euo pipefail

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
NAMESPACE="bookinfo"
WAIT_SECONDS=${WAIT_SECONDS:-180}  # override with: make all WAIT_SECONDS=60
KUBECTL="${KUBECTL:-oc}"

echo "Removing fault injection manifests…"
$KUBECTL delete -f "$FIXTURE_DIR/manifests.yaml" --ignore-not-found

echo "Removing any AuthorizationPolicies created by the agent during the test…"
$KUBECTL delete authorizationpolicy allow-reviews-to-ratings  -n "$NAMESPACE" --ignore-not-found || true
$KUBECTL delete authorizationpolicy ratings-viewer             -n "$NAMESPACE" --ignore-not-found || true
$KUBECTL get authorizationpolicy -n "$NAMESPACE" --no-headers 2>/dev/null \
  | grep -i ratings | awk '{print $1}' \
  | xargs -r $KUBECTL delete authorizationpolicy -n "$NAMESPACE" --ignore-not-found || true

echo "Waiting ${WAIT_SECONDS}s for Istio metrics to stabilise after fault removal…"
sleep "$WAIT_SECONDS"
echo "Cleanup complete — fault injection and agent-created resources removed."
