#!/bin/bash
set -e

echo "Scenario 01 — Payments API Failure"
echo ""
echo "=== Rolling back reporting-service to v1.0.1 ==="
oc -n shared-services set image deployment/reporting-service reporting-service=quay.io/afalossi/ts01-reporting-service:v1.0.1
oc -n shared-services rollout status deployment/reporting-service --timeout=120s

echo ""
echo "Done. reporting-service is now running v1.0.1."
