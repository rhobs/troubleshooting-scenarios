#!/usr/bin/env bash
set -euo pipefail

KUBECTL=${KUBECTL:-oc}
NAMESPACE=${NAMESPACE:-kubevirt-scenarios}
FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"

# shellcheck source=SCRIPTDIR/../scripts/require-kvm.sh disable=SC1091
source "$(cd "$(dirname "$0")/../scripts" && pwd)/require-kvm.sh"
require_kvm

echo "==> Deploying VM crashloop scenario in namespace ${NAMESPACE}..."
echo "    VM has a cloud-init runcmd that immediately shuts it down, causing a restart loop."

${KUBECTL} create namespace "${NAMESPACE}" --dry-run=client -o yaml | ${KUBECTL} apply -f -
${KUBECTL} apply -f "${FIXTURE_DIR}/vm.yaml" -n "${NAMESPACE}"

echo "==> Waiting for crashloop to become visible (up to 180s)..."
for _ in $(seq 1 18); do
  vmi_phase=$(${KUBECTL} get vmi web-server-vm -n "${NAMESPACE}" \
    -o jsonpath='{.status.phase}' 2>/dev/null || true)
  if [[ "${vmi_phase}" == "Succeeded" || "${vmi_phase}" == "Failed" ]]; then
    # Wait for at least 2 restart cycles so the crashloop pattern is clearly visible
    sleep 40
    break
  fi
  vm_status=$(${KUBECTL} get vm web-server-vm -n "${NAMESPACE}" \
    -o jsonpath='{.status.printableStatus}' 2>/dev/null || true)
  if [[ "${vm_status}" == "CrashLoopBackOff" || "${vm_status}" == "Stopped" ]]; then
    break
  fi
  sleep 10
done

echo "==> VM status:"
${KUBECTL} get vm web-server-vm -n "${NAMESPACE}" -o wide 2>/dev/null || echo "    VM not found"
echo ""
echo "==> Recent events:"
${KUBECTL} get events -n "${NAMESPACE}" --sort-by=.lastTimestamp 2>/dev/null \
  | grep "web-server" \
  | tail -10 || true
echo ""
echo "==> Setup complete. Ask the AI:"
echo '    "VM web-server-vm in '"${NAMESPACE}"' keeps restarting. It starts but dies within seconds. Why?"'
