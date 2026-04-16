#!/bin/bash
set -e

echo "=== Fixing probes on reconciliation-service ==="
oc set probe deployment/reconciliation-service -n shared-services \
  --readiness --open-tcp=8080 --initial-delay-seconds=3 --period-seconds=5 --failure-threshold=3
oc set probe deployment/reconciliation-service -n shared-services \
  --liveness --open-tcp=8080 --initial-delay-seconds=3 --period-seconds=5 --failure-threshold=3

oc -n shared-services rollout status deployment/reconciliation-service --timeout=120s

echo ""
echo "Done. reconciliation-service is running normally."
