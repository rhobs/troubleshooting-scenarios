#!/bin/bash
set -e

# Manifests, break.sh and fix.sh pull from this registry, so pushing elsewhere has no effect.
REGISTRY="quay.io/openshiftanalytics"
if [ -n "$1" ] && [ "$1" != "$REGISTRY" ]; then
  echo "Error: REGISTRY must be $REGISTRY (got: $1). Update the manifests and scripts first to use another one." >&2
  exit 1
fi

echo "Scenario 01 — Payments API Failure"
echo ""
echo "=== Building images ==="
podman build -t "${REGISTRY}"/ts01-reporting-service:v1.0.1 reporting-service/v1.0.1/
podman build -t "${REGISTRY}"/ts01-reporting-service:v1.0.2 reporting-service/v1.0.2/
podman build -t "${REGISTRY}"/ts01-payments-api:v1.0.1 payments-api/

echo ""
echo "=== Pushing images ==="
podman push "${REGISTRY}"/ts01-reporting-service:v1.0.1
podman push "${REGISTRY}"/ts01-reporting-service:v1.0.2
podman push "${REGISTRY}"/ts01-payments-api:v1.0.1

echo ""
echo "Done."
