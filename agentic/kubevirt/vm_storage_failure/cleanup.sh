#!/usr/bin/env bash
set -euo pipefail

KUBECTL=${KUBECTL:-oc}
NAMESPACE=${NAMESPACE:-kubevirt-scenarios}

echo "==> Cleaning up vm_storage_failure scenario..."
${KUBECTL} delete vm production-db-vm -n "${NAMESPACE}" --ignore-not-found
${KUBECTL} delete dv production-db-vm-volume -n "${NAMESPACE}" --ignore-not-found
${KUBECTL} delete pvc production-db-vm-volume -n "${NAMESPACE}" --ignore-not-found
echo "==> Cleanup complete."
