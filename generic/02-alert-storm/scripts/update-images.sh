#!/bin/bash
set -e

if [ -z "$1" ]; then
  echo "Error: REGISTRY is required. Usage: make update-images REGISTRY=quay.io/..." >&2
  exit 1
fi
REGISTRY="$1"

echo "Scenario 02 — Alert Storm"
echo ""
echo "=== Building images ==="
podman build -t ${REGISTRY}/ts02-payments-api:latest images/payments-api/
podman build -t ${REGISTRY}/ts02-checkout-service:latest images/checkout-service/
podman build -t ${REGISTRY}/ts02-order-processor:latest images/order-processor/
podman build -t ${REGISTRY}/ts02-refund-service:latest images/refund-service/
podman build -t ${REGISTRY}/ts02-notification-service:latest images/notification-service/

echo ""
echo "=== Pushing images ==="
podman push ${REGISTRY}/ts02-payments-api:latest
podman push ${REGISTRY}/ts02-checkout-service:latest
podman push ${REGISTRY}/ts02-order-processor:latest
podman push ${REGISTRY}/ts02-refund-service:latest
podman push ${REGISTRY}/ts02-notification-service:latest

echo ""
echo "Done."
