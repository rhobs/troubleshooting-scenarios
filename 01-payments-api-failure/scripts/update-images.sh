#!/bin/bash
set -e

if [ -z "$1" ]; then
  echo "Error: REGISTRY is required. Usage: make update-images REGISTRY=quay.io/..." >&2
  exit 1
fi
REGISTRY="$1"

echo "=== Building images ==="
podman build -t ${REGISTRY}/scenario1-reporting-service:v1.0.1 reporting-service/v1.0.1/
podman build -t ${REGISTRY}/scenario1-reporting-service:v1.0.2 reporting-service/v1.0.2/
podman build -t ${REGISTRY}/scenario1-payments-api:v1.0.1 payments-api/

echo ""
echo "=== Pushing images ==="
podman push ${REGISTRY}/scenario1-reporting-service:v1.0.1
podman push ${REGISTRY}/scenario1-reporting-service:v1.0.2
podman push ${REGISTRY}/scenario1-payments-api:v1.0.1

echo ""
echo "Done."
