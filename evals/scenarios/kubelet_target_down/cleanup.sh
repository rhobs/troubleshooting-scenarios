#!/usr/bin/env bash
set -euo pipefail

SCENARIO_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_DIR="$(cd "$SCENARIO_DIR/../../../scripts" && pwd)"
# shellcheck source=scripts/scenario-namespace.sh
source "$SCRIPT_DIR/scenario-namespace.sh"
FIXTURE_DIR="$SCENARIO_DIR/fixtures"

"$SCRIPT_DIR/check-prerequisites.sh"

NS="batch-processor"
DEPLOYMENT="report-generator"
CLEANUP_TIMEOUT="${CLEANUP_TIMEOUT:-300}"

# Check if we own this namespace before cleaning up
if scenario_namespace_owned "$NS" oc; then
  :
else
  status=$?
  if [ "$status" -eq 1 ]; then exit 0; fi
  exit "$status"
fi

echo "Cleaning up $NS namespace..."

# First scale down to 0 to stop creating new pods
if oc get deployment/"$DEPLOYMENT" -n "$NS" >/dev/null 2>&1; then
  echo "Scaling deployment to 0..."
  oc scale deployment/"$DEPLOYMENT" -n "$NS" --replicas=0 --timeout=30s 2>/dev/null || true
fi

# Force delete all pods to avoid waiting for long grace periods
echo "Force deleting all pods..."
oc delete pods -n "$NS" --all --grace-period=0 --force 2>/dev/null || true

# Delete the deployment
echo "Deleting deployment..."
oc delete -f "$FIXTURE_DIR/deployment.yaml" --ignore-not-found --wait=false

# Delete namespace - this will handle terminating pods
# Note: Namespace deletion will wait for pods but we set a timeout
echo "Deleting namespace (may take time due to terminating pods)..."
if ! oc delete namespace "$NS" --ignore-not-found --timeout="${CLEANUP_TIMEOUT}s" 2>/dev/null; then
  echo "WARNING: Namespace deletion timed out after ${CLEANUP_TIMEOUT}s"
  echo "Checking remaining pods..."
  oc get pods -n "$NS" --no-headers 2>/dev/null || true

  # Force cleanup by removing finalizers if namespace is stuck
  if oc get namespace "$NS" >/dev/null 2>&1; then
    echo "Attempting to force namespace deletion..."
    oc patch namespace "$NS" -p '{"metadata":{"finalizers":[]}}' --type=merge 2>/dev/null || true
  fi
fi

# Wait for namespace to be fully gone
echo "Verifying namespace deletion..."
for _ in $(seq 1 90); do
  NS_UID=$(oc get namespace "$NS" --ignore-not-found -o jsonpath='{.metadata.uid}' 2>/dev/null)
  if [ -z "$NS_UID" ]; then
    rm -f "$SCENARIO_STATE_DIR/$NS.uid"
    echo "Cleanup complete: namespace/$NS removed"
    exit 0
  fi
  sleep 2
done

echo "ERROR: namespace/$NS is still present after cleanup" >&2
exit 1
