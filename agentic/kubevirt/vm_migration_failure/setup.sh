#!/usr/bin/env bash
set -euo pipefail

KUBECTL=${KUBECTL:-oc}
NAMESPACE=${NAMESPACE:-kubevirt-scenarios}
FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"

# shellcheck source=SCRIPTDIR/../scripts/require-kvm.sh disable=SC1091
source "$(cd "$(dirname "$0")/../scripts" && pwd)/require-kvm.sh"
require_kvm

# Pin VM to a worker node (auto-detect if not provided)
NODE_NAME="${NODE_NAME:-}"
if [[ -z "${NODE_NAME}" ]]; then
  # || true prevents set -e from aborting on non-zero exit (e.g., no nodes match label)
  NODE_NAME=$(${KUBECTL} get nodes -l node-role.kubernetes.io/worker \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true
  if [[ -z "${NODE_NAME}" ]]; then
    # Fallback: pick the first schedulable node (compact/SNO clusters)
    NODE_NAME=$(${KUBECTL} get nodes --no-headers 2>/dev/null \
      | awk '!/SchedulingDisabled/ {print $1; exit}') || true
  fi
  if [[ -z "${NODE_NAME}" ]]; then
    echo "ERROR: Could not determine a schedulable node. Set NODE_NAME or check cluster access."
    exit 1
  fi
fi

# Note: The scenario works on any cluster size. The hostname nodeSelector ensures
# migration fails because no other node can match the exact same hostname.

echo "==> Deploying VM migration failure scenario in namespace ${NAMESPACE}..."
echo "    VM is pinned to node ${NODE_NAME} via nodeSelector. Migration will fail."

${KUBECTL} create namespace "${NAMESPACE}" --dry-run=client -o yaml | ${KUBECTL} apply -f -

# Apply base VM, then immediately patch nodeSelector before VMI is created.
# runStrategy:Always starts the VM on apply; the patch lands before image pull completes.
${KUBECTL} apply -f "${FIXTURE_DIR}/vm.yaml" -n "${NAMESPACE}"
${KUBECTL} patch vm critical-app-vm -n "${NAMESPACE}" --type=merge -p \
  "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"${NODE_NAME}\"}}}}}"

# Restart to ensure the VMI picks up the patched nodeSelector
${KUBECTL} delete vmi critical-app-vm -n "${NAMESPACE}" --ignore-not-found 2>/dev/null || true
sleep 5

echo "==> Waiting for VM to be ready..."
if ! ${KUBECTL} wait --for=condition=Ready vm/critical-app-vm -n "${NAMESPACE}" --timeout=300s 2>/dev/null; then
  echo "ERROR: VM not ready after 300s. Cannot trigger migration."
  exit 1
fi

echo "==> VM status:"
${KUBECTL} get vm critical-app-vm -n "${NAMESPACE}" -o wide
echo ""
echo "==> VMI running on node:"
${KUBECTL} get vmi critical-app-vm -n "${NAMESPACE}" -o jsonpath='{.status.nodeName}' 2>/dev/null; echo ""

echo ""
echo "==> Triggering a migration so the failure state exists for the eval..."
${KUBECTL} delete vmim critical-app-vm-migration -n "${NAMESPACE}" --ignore-not-found 2>/dev/null || true
cat <<EOF | ${KUBECTL} apply -n "${NAMESPACE}" -f -
apiVersion: kubevirt.io/v1
kind: VirtualMachineInstanceMigration
metadata:
  name: critical-app-vm-migration
spec:
  vmiName: critical-app-vm
EOF

echo "==> Waiting for migration to fail (expected due to nodeSelector pinning)..."
${KUBECTL} wait \
  --for=jsonpath='{.status.phase}'=Failed \
  vmim/critical-app-vm-migration \
  -n "${NAMESPACE}" \
  --timeout=180s 2>/dev/null || true

echo ""
echo "==> Migration status:"
${KUBECTL} get vmim -n "${NAMESPACE}" 2>/dev/null || true
migration_phase=$(${KUBECTL} get vmim critical-app-vm-migration -n "${NAMESPACE}" \
  -o jsonpath='{.status.phase}' 2>/dev/null || true)
echo "    Final VMIM phase: ${migration_phase:-unknown}"
echo ""
echo "==> Setup complete. Ask the AI:"
echo '    "I tried to migrate VM critical-app-vm in '"${NAMESPACE}"' but it failed. Why?"'
