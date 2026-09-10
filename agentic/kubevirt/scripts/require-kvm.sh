#!/usr/bin/env bash
# KVM availability check for kubevirt scenarios.
#
# Sourced by setup.sh:  source require-kvm.sh; require_kvm
#   Exits the caller with 0 (skip) if VMs cannot run.
#
# Standalone:  bash require-kvm.sh --check
#   Exits 0 if VMs can run (KVM devices or emulation), 1 if not. No output.

KUBECTL="${KUBECTL:-oc}"
CNV_NS="${CNV_NS:-openshift-cnv}"

_vms_can_run() {
  local kvm_total
  kvm_total=$(${KUBECTL} get nodes -l node-role.kubernetes.io/worker \
    -o jsonpath='{range .items[*]}{.status.allocatable.devices\.kubevirt\.io/kvm}{"\n"}{end}' 2>/dev/null \
    | awk '{s+=$1} END{print s+0}')
  [[ "${kvm_total}" -gt 0 ]] && return 0

  local emulation
  emulation=$(${KUBECTL} get kubevirt -n "${CNV_NS}" \
    -o jsonpath='{.items[0].spec.configuration.developerConfiguration.useEmulation}' 2>/dev/null)
  [[ "${emulation}" == "true" ]]
}

require_kvm() {
  if ! _vms_can_run; then
    echo "SKIP: No KVM devices and emulation is not enabled. This scenario requires running VMs."
    exit 0
  fi
}

if [[ "${1:-}" == "--check" ]]; then
  _vms_can_run
fi
