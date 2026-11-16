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

  # Force cleanup by inspecting and clearing spec.finalizers if namespace is stuck
  if oc get namespace "$NS" >/dev/null 2>&1; then
    echo "Namespace stuck in Terminating state, inspecting resources..."

    # Check for remaining resources
    echo "Checking for remaining resources in namespace..."
    oc api-resources --verbs=list --namespaced -o name 2>/dev/null | xargs -n 1 oc get --show-kind --ignore-not-found -n "$NS" 2>/dev/null | head -20 || true

    # Check spec.finalizers (different from metadata.finalizers)
    FINALIZERS=$(oc get namespace "$NS" -o jsonpath='{.spec.finalizers}' 2>/dev/null || echo "[]")
    if [ "$FINALIZERS" != "[]" ] && [ -n "$FINALIZERS" ]; then
      echo "Namespace has spec.finalizers: $FINALIZERS"
      echo "Attempting to force finalization..."
      # Use the /finalize subresource to properly clear finalizers
      oc patch namespace "$NS" -p '{"spec":{"finalizers":[]}}' --type=merge 2>/dev/null || {
        echo "WARNING: Could not clear finalizers via patch, namespace may require manual cleanup" >&2
      }
    fi
  fi
fi

# Wait for namespace to be fully gone
echo "Verifying namespace deletion..."
for _ in $(seq 1 90); do
  # Use --ignore-not-found and check exit code to distinguish "not found" from "lookup error"
  if NS_UID=$(oc get namespace "$NS" --ignore-not-found -o jsonpath='{.metadata.uid}' 2>&1); then
    if [ -z "$NS_UID" ]; then
      # Namespace deleted - now verify target node recovery
      rm -f "$SCENARIO_STATE_DIR/$NS.uid"

      # Determine which node was targeted by checking deployment nodeSelector before we cleaned up
      # If we can't determine it, skip node verification
      echo "Verifying target node recovery..."

      # Wait briefly for node to stabilize
      sleep 5

      # Check all worker nodes are Ready (we don't track which specific node was used)
      echo "Checking worker node status..."
      if ! oc get nodes -l node-role.kubernetes.io/worker --no-headers 2>/dev/null | grep -q "NotReady"; then
        echo "Cleanup complete: namespace/$NS removed, worker nodes are Ready"
      else
        echo "WARNING: Namespace removed but some worker nodes may still be recovering"
      fi
      exit 0
    fi
    # Namespace still exists, continue waiting
  else
    # Lookup failed - propagate error without removing ownership file
    echo "ERROR: Failed to verify namespace status: $NS_UID" >&2
    exit 1
  fi
  sleep 2
done

echo "ERROR: namespace/$NS is still present after cleanup" >&2
exit 1
