#!/bin/bash
set -e

echo "Scenario 02 — Alert Storm"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "=== Enabling user workload monitoring ==="
oc apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-monitoring-config
  namespace: openshift-monitoring
data:
  config.yaml: |
    enableUserWorkload: true
EOF

echo ""
echo "=== Cleaning up existing namespace ==="
oc delete namespace payments --ignore-not-found --wait

echo ""
echo "=== Creating namespace ==="
oc apply -f manifests/00-namespace.yaml

echo ""
echo "=== Deploying healthy ConfigMap ==="
oc apply -f manifests/configmaps/payments-api-config-healthy.yaml

echo ""
echo "=== Deploying services ==="
oc apply -f manifests/01-payments-api.yaml
oc apply -f manifests/02-checkout-service.yaml
oc apply -f manifests/03-order-processor.yaml
oc apply -f manifests/04-refund-service.yaml
oc apply -f manifests/05-notification-service.yaml
oc apply -f manifests/06-prometheusrules.yaml

echo ""
echo "=== Waiting for deployments to be ready ==="
for deploy in payments-api checkout-service order-processor refund-service notification-service; do
  echo "  Waiting for ${deploy}..."
  oc -n payments wait --for=condition=available deployment/${deploy} --timeout=120s
done

echo ""
echo "Done. All pods running in the 'payments' namespace."
