#!/usr/bin/env bash
set -euo pipefail

KUBECTL=${KUBECTL:-oc}
NAMESPACE=${NAMESPACE:-kubevirt-scenarios}

echo "==> Cleaning up vm_crashloop scenario..."
${KUBECTL} delete vm web-server-vm -n "${NAMESPACE}" --ignore-not-found
echo "==> Cleanup complete."
