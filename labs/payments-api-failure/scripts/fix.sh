#!/bin/bash
set -e

echo "Scenario 01 — Payments API Failure"
echo ""

if oc get namespace shared-services &>/dev/null; then
  SERVICES_NS="shared-services"
else
  SERVICES_NS="payments"
fi

echo "=== Rolling back reporting-service to v1.0.1 ==="
oc -n "$SERVICES_NS" set image deployment/reporting-service reporting-service=quay.io/openshiftanalytics/ts01-reporting-service:v1.0.1
oc -n "$SERVICES_NS" rollout status deployment/reporting-service --timeout=120s

echo ""
echo "Done. reporting-service is now running v1.0.1."
