#!/usr/bin/env bash
set -euo pipefail

SCENARIO_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_DIR="$(cd "$SCENARIO_DIR/../../../scripts" && pwd)"
FIXTURE_DIR="$SCENARIO_DIR/fixtures"

"$SCRIPT_DIR/check-prerequisites.sh"

NS="batch-processor"
DEPLOYMENT="report-generator"
CLEANUP_TIMEOUT="${CLEANUP_TIMEOUT:-300}"

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
ELAPSED=0
while [ "$ELAPSED" -lt 180 ]; do
  if ! oc get namespace "$NS" >/dev/null 2>&1; then
    echo "Cleanup complete: removed $NS namespace and resources"
    exit 0
  fi
  sleep 5
  ELAPSED=$((ELAPSED + 5))
done

echo "WARNING: Namespace $NS may still exist. Manual cleanup may be required." >&2
oc get namespace "$NS" 2>/dev/null || true
exit 1
