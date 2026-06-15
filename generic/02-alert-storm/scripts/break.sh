#!/bin/bash
set -e

echo "Scenario 02 — Alert Storm"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "=== Triggering failure scenario ==="

echo "  Applying broken ConfigMap for payments-api..."
oc apply -f manifests/configmaps/payments-api-config-broken.yaml

echo "  Reducing payments-api memory limit to 128Mi..."
CONFIG_HASH=$(oc get configmap payments-api-config -n payments -o jsonpath='{.data}' | sha256sum | cut -d' ' -f1)
oc patch deployment payments-api -n payments --type=strategic -p \
  "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"checksum/config\":\"${CONFIG_HASH}\"}},\"spec\":{\"containers\":[{\"name\":\"payments-api\",\"resources\":{\"requests\":{\"memory\":\"64Mi\"},\"limits\":{\"memory\":\"128Mi\"}}}]}}}}"

TOKEN=$(oc whoami -t)
THANOS_HOST=$(oc -n openshift-monitoring get route thanos-querier -o jsonpath='{.spec.host}')

echo ""
echo "Waiting for payments-api to OOMKill and cascade to develop (~5 minutes)..."
while true; do
  ALERT_COUNT=$(curl -sk -H "Authorization: Bearer ${TOKEN}" \
    "https://${THANOS_HOST}/api/v1/alerts" 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(sum(1 for a in data.get('data',{}).get('alerts',[])
          if a['labels'].get('namespace')=='payments'
          and a['state']=='firing'))" 2>/dev/null || echo "0")
  echo "  Firing alerts: ${ALERT_COUNT}"
  if [ "$ALERT_COUNT" -ge 5 ] 2>/dev/null; then
    break
  fi
  sleep 15
done

echo ""
echo "Done. Alert storm is active — ${ALERT_COUNT} alerts firing."
