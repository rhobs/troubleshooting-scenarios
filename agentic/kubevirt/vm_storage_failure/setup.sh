#!/usr/bin/env bash
set -euo pipefail

KUBECTL=${KUBECTL:-oc}
NAMESPACE=${NAMESPACE:-kubevirt-scenarios}
FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"

echo "==> Deploying VM storage failure scenario in namespace ${NAMESPACE}..."
echo "    VM uses non-existent StorageClass 'premium-nvme-storage' and will be stuck in Provisioning."

${KUBECTL} create namespace "${NAMESPACE}" --dry-run=client -o yaml | ${KUBECTL} apply -f -
${KUBECTL} apply -f "${FIXTURE_DIR}/vm.yaml" -n "${NAMESPACE}"

echo "==> Waiting 15s for DataVolume to be created..."
sleep 15

echo "==> VM status:"
${KUBECTL} get vm production-db-vm -n "${NAMESPACE}" -o wide 2>/dev/null || echo "    VM not found"
echo ""
echo "==> DataVolume status:"
${KUBECTL} get dv production-db-vm-volume -n "${NAMESPACE}" 2>/dev/null || echo "    No DataVolume"
echo ""
echo "==> Setup complete. Ask the AI:"
echo '    "Why is VM production-db-vm not starting in namespace '"${NAMESPACE}"'?"'
