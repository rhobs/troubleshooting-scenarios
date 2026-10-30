#!/bin/bash
set -e

echo "Scenario 01 — Payments API Failure"
echo ""

if oc get namespace shared-services &>/dev/null; then
  SERVICES_NS="shared-services"
else
  SERVICES_NS="payments"
fi

echo "=== Rolling out reporting-service v1.0.2 ==="
oc -n "$SERVICES_NS" set image deployment/reporting-service reporting-service=quay.io/openshiftanalytics/ts01-reporting-service:v1.0.2
oc -n "$SERVICES_NS" rollout status deployment/reporting-service --timeout=120s

ROUTE=$(oc -n payments get route payments-api -o jsonpath='{.spec.host}')

echo ""
echo "Waiting for connection pool exhaustion (~3 minutes)..."
while true; do
  STATUS=$(curl -s -o /dev/null -w '%{http_code}' "http://${ROUTE}/api/v1/process-payment" 2>/dev/null || echo "000")
  if [ "$STATUS" = "503" ]; then
    break
  fi
  sleep 5
done
echo "payments-api is returning 503."

SCRIPT_DIR="$(cd "$(dirname "$0")/../../../scripts" && pwd)"
"$SCRIPT_DIR/wait-for-alert.sh" "PaymentErrorRateHigh" "critical"
