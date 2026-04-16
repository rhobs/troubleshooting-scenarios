#!/bin/bash
set -e

echo "=== Rolling out reporting-service v1.0.2 ==="
oc -n shared-services set image deployment/reporting-service reporting-service=quay.io/afalossi/ts01-reporting-service:v1.0.2
oc -n shared-services rollout status deployment/reporting-service --timeout=120s

ROUTE=$(oc -n payments get route payments-api -o jsonpath='{.spec.host}')
TOKEN=$(oc whoami -t)
THANOS_HOST=$(oc -n openshift-monitoring get route thanos-querier -o jsonpath='{.spec.host}')

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

echo "Waiting for PaymentErrorRateHigh critical alert to fire..."
while true; do
  ALERT_COUNT=$(curl -sk -H "Authorization: Bearer ${TOKEN}" \
    "https://${THANOS_HOST}/api/v1/alerts" 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(sum(1 for a in data.get('data',{}).get('alerts',[])
          if a['labels'].get('alertname')=='PaymentErrorRateHigh'
          and a['labels'].get('severity')=='critical'
          and a['state']=='firing'))" 2>/dev/null || echo "0")
  if [ "$ALERT_COUNT" -gt 0 ] 2>/dev/null; then
    break
  fi
  sleep 10
done

echo "Done. PaymentErrorRateHigh critical alert is firing — scenario is ready."
