#!/usr/bin/env bash
set -euo pipefail

KUBECTL=${KUBECTL:-oc}
NAMESPACE=${NAMESPACE:-kubevirt-scenarios}

echo "==> Cleaning up vm_migration_failure scenario..."
${KUBECTL} delete vm critical-app-vm -n "${NAMESPACE}" --ignore-not-found
${KUBECTL} delete vmim -n "${NAMESPACE}" --all --ignore-not-found 2>/dev/null || true
echo "==> Cleanup complete."
