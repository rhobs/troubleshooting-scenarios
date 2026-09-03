#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../scripts" && pwd)/check-prerequisites.sh"

NS="cache-tier"

oc delete -f "$(cd "$(dirname "$0")/fixtures" && pwd)/prometheusrule.yaml" --ignore-not-found
oc delete deployment memcached -n "$NS" --ignore-not-found --wait=false
oc wait --for=delete pod -l app=memcached -n "$NS" --timeout=120s || true
oc delete pvc memcached-data-pvc -n "$NS" --ignore-not-found
oc delete svc memcached -n "$NS" --ignore-not-found
oc delete namespace "$NS" --ignore-not-found

echo "Cleanup complete: removed cache-tier namespace and resources"
