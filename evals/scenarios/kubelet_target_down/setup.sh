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
APP_LABEL="app=report-generator"
STRESS_TIMEOUT="${STRESS_TIMEOUT:-1200}"

# Find the worker node with smallest allocatable capacity
echo "Finding worker node with smallest allocatable capacity..."
TARGET_NODE=$("$SCRIPT_DIR/find-smallest-node.sh")
echo "Selected node: $TARGET_NODE"

# Create namespace with ownership tracking
echo "Creating namespace $NS..."
scenario_create_namespace "$NS" "$FIXTURE_DIR/namespace.yaml" oc

# Apply deployment
echo "Applying deployment..."
oc apply -f "$FIXTURE_DIR/deployment.yaml"

# Patch deployment with nodeSelector to pin pods to target node
echo "Patching deployment with nodeSelector pinned to $TARGET_NODE..."
oc patch deployment/"$DEPLOYMENT" -n "$NS" --type=merge \
  -p "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"$TARGET_NODE\"}}}}}"

# Verify deployment exists with 0 replicas
echo "Verifying deployment is ready..."
REPLICAS=$(oc get deployment/"$DEPLOYMENT" -n "$NS" -o jsonpath='{.spec.replicas}')
if [ "$REPLICAS" != "0" ]; then
  echo "ERROR: Deployment does not have 0 replicas as expected (got $REPLICAS)" >&2
  exit 1
fi

# Function to check if TargetDown alert is firing for kubelet and our node is unhealthy
check_alert() {
  local target_node="$1"
  local token
  local thanos_host

  token=$(oc whoami -t 2>/dev/null || oc create token prometheus-k8s -n openshift-monitoring --duration=10m)
  thanos_host=$(oc -n openshift-monitoring get route thanos-querier -o jsonpath='{.spec.host}')

  # First check if TargetDown alert is firing or pending for kubelet
  # Note: -k (insecure) is used as clusters typically use self-signed ingress certs
  local alert_firing
  alert_firing=$(curl -sk --max-time 10 -H "Authorization: Bearer ${token}" \
    "https://${thanos_host}/api/v1/alerts" 2>/dev/null |
    python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for alert in data.get('data', {}).get('alerts', []):
        state = alert.get('state')
        if state in ('firing', 'pending'):
            labels = alert.get('labels', {})
            if labels.get('alertname') == 'TargetDown' and labels.get('job') == 'kubelet':
                print('1')
                sys.exit(0)
    print('0')
except Exception:
    print('0')
" 2>/dev/null || echo "0")

  if [ "$alert_firing" != "1" ]; then
    echo "0"
    return
  fi

  # Alert is firing, now check if our specific node's kubelet target is down
  # Note: -k (insecure) is used as clusters typically use self-signed ingress certs
  curl -sk --max-time 10 -H "Authorization: Bearer ${token}" \
    "https://${thanos_host}/api/v1/targets" 2>/dev/null |
    python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    target_node = '${target_node}'

    for target in data.get('data', {}).get('activeTargets', []):
        labels = target.get('labels', {})
        if labels.get('job') == 'kubelet' and labels.get('node') == target_node:
            if target.get('health') != 'up':
                print('1')
                sys.exit(0)

    print('0')
except Exception:
    print('0')
" 2>/dev/null || echo "0"
}

# Kubelet stress loop
echo "Starting kubelet stress test (timeout: ${STRESS_TIMEOUT}s)..."
echo "Target: TargetDown alert for kubelet on $TARGET_NODE"

START_TIME=$(date +%s)
ITERATION=0

while true; do
  CURRENT_TIME=$(date +%s)
  ELAPSED=$((CURRENT_TIME - START_TIME))

  if [ "$ELAPSED" -ge "$STRESS_TIMEOUT" ]; then
    echo "ERROR: TargetDown alert did not become active within ${STRESS_TIMEOUT}s after $ITERATION iterations" >&2
    exit 1
  fi

  ITERATION=$((ITERATION + 1))
  echo "==> Iteration $ITERATION (elapsed ${ELAPSED}s / ${STRESS_TIMEOUT}s)"

  # Scale to 100 replicas
  echo "Scaling $DEPLOYMENT to 100 replicas..."
  oc scale deployment/"$DEPLOYMENT" -n "$NS" --replicas=100 --timeout=30s --request-timeout=35s 2>/dev/null || {
    echo "WARNING: Scale command timed out or failed, continuing..."
  }

  # Wait for pods to start appearing (don't wait for Ready)
  echo "Waiting for pods to be created..."
  WAIT_PODS=0
  while [ "$WAIT_PODS" -lt 60 ]; do
    POD_COUNT=$(oc get pods -n "$NS" -l "$APP_LABEL" --no-headers --request-timeout=10s 2>/dev/null | wc -l)
    if [ "$POD_COUNT" -ge 50 ]; then
      echo "Found $POD_COUNT pods"
      break
    fi
    sleep 2
    WAIT_PODS=$((WAIT_PODS + 2))
  done

  # Delete all pods by label (respects pod's terminationGracePeriodSeconds)
  echo "Deleting all pods with label $APP_LABEL..."
  oc delete pods -n "$NS" -l "$APP_LABEL" --wait=false --request-timeout=30s 2>/dev/null || true

  # Give it a moment for the kubelet stress to build up
  sleep 5

  # Check if TargetDown alert is firing for our kubelet
  echo "Checking for TargetDown alert..."
  ALERT_FOUND=$(check_alert "$TARGET_NODE")

  if [ "$ALERT_FOUND" = "1" ]; then
    echo "SUCCESS: TargetDown alert is active for kubelet on $TARGET_NODE after $ITERATION iterations"
    echo "Setup complete: kubelet_target_down scenario is ready"
    exit 0
  fi

  echo "Alert not active yet, continuing..."
  sleep 3
done
