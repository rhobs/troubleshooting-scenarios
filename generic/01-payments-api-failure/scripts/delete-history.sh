#!/bin/bash
set -euo pipefail

echo "Scenario 01 — Payments API Failure"
echo ""

PLATFORM_NS="openshift-monitoring"
USER_NS="openshift-user-workload-monitoring"

PROMETHEUS_PODS=(
  "$USER_NS:prometheus-user-workload-0"
  "$USER_NS:prometheus-user-workload-1"
  "$PLATFORM_NS:prometheus-k8s-0"
  "$PLATFORM_NS:prometheus-k8s-1"
)

echo "Note: If the script hangs, press Ctrl+C and run it again."
echo ""
echo "=== Resetting Prometheus TSDB ==="
for entry in "${PROMETHEUS_PODS[@]}"; do
  ns="${entry%%:*}"
  pod="${entry##*:}"
  echo "  Cleaning $pod in $ns"
  oc exec -n "$ns" "$pod" -c prometheus -- sh -c 'rm -rf /prometheus/wal /prometheus/chunks_head /prometheus/data'
done

echo "Restarting Prometheus pods..."
oc delete pod -n "$USER_NS" prometheus-user-workload-0 prometheus-user-workload-1
oc delete pod -n "$PLATFORM_NS" prometheus-k8s-0 prometheus-k8s-1

echo ""
echo "=== Deleting events ==="
oc delete events --all -n payments
oc delete events --all -n shared-services

echo ""
echo "=== Restarting demo pods ==="
oc delete pods --all -n payments
oc delete pods --all -n shared-services

echo ""
echo "Done. All Prometheus and demo pods are restarting."
