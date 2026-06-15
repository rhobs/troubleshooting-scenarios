#!/bin/bash
set -e

echo "Scenario 02 — Alert Storm"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "=== Restoring healthy state ==="

echo "  Restoring healthy ConfigMap for payments-api..."
oc apply -f manifests/configmaps/payments-api-config-healthy.yaml

echo "  Restoring payments-api memory limit to 256Mi..."
CONFIG_HASH=$(oc get configmap payments-api-config -n payments -o jsonpath='{.data}' | sha256sum | cut -d' ' -f1)
oc patch deployment payments-api -n payments --type=strategic -p \
  "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"checksum/config\":\"${CONFIG_HASH}\"}},\"spec\":{\"containers\":[{\"name\":\"payments-api\",\"resources\":{\"requests\":{\"memory\":\"128Mi\"},\"limits\":{\"memory\":\"256Mi\"}}}]}}}}"

echo ""
echo "Done. payments-api will restart and all services will auto-recover."
