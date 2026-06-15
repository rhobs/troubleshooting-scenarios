#!/bin/bash
set -e

echo "Scenario 01 — Payments API Failure"
echo ""
echo "=== Misconfiguring probes on reconciliation-service ==="
oc set probe deployment/reconciliation-service -n shared-services \
  --readiness --get-url=http://:8443/ --initial-delay-seconds=3 --period-seconds=5 --failure-threshold=3
oc set probe deployment/reconciliation-service -n shared-services \
  --liveness --get-url=http://:8443/ --initial-delay-seconds=3 --period-seconds=5 --failure-threshold=3

oc -n shared-services rollout status deployment/reconciliation-service --timeout=60s || true

echo ""
echo "Done. reconciliation-service will enter CrashLoopBackOff (probes on wrong port)."
