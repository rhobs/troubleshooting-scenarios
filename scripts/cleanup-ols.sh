#!/usr/bin/env bash
set -euo pipefail

echo "==> Removing OLS from openshift-lightspeed..."

# ClusterRoleBindings remain after namespace deletion. Remove only our bindings.
if ! oc delete clusterrolebinding -l troubleshooting-scenarios/rbac=agentic --ignore-not-found; then
  echo "ERROR: Cannot remove managed Agentic bindings. Run cleanup with cluster-admin access." >&2
  exit 1
fi

oc delete olsconfig cluster --ignore-not-found 2>/dev/null || true
oc delete secret creds-classic-openai -n openshift-lightspeed --ignore-not-found 2>/dev/null || true

# Remove Subscription + CSV
CSV=$(oc get subscription lightspeed-operator -n openshift-lightspeed \
  -o jsonpath='{.status.currentCSV}' 2>/dev/null || true)
oc delete subscription lightspeed-operator -n openshift-lightspeed --ignore-not-found 2>/dev/null || true
if [ -n "$CSV" ]; then
  oc delete csv "$CSV" -n openshift-lightspeed --ignore-not-found 2>/dev/null || true
fi

oc delete operatorgroup openshift-lightspeed -n openshift-lightspeed --ignore-not-found 2>/dev/null || true
oc delete namespace openshift-lightspeed --ignore-not-found 2>/dev/null || true

echo "==> OLS cleanup complete."
