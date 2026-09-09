#!/usr/bin/env bash
# Remove the OpenShift Virtualization operator and all its resources.
# Idempotent: succeeds if CNV is already absent.
set -euo pipefail

CNV_NS="${CNV_NS:-openshift-cnv}"
KUBECTL="${KUBECTL:-oc}"

echo "==> Removing OpenShift Virtualization..."

# 1. Delete the operand (triggers cleanup of all managed resources)
${KUBECTL} delete hyperconverged kubevirt-hyperconverged -n "${CNV_NS}" --ignore-not-found --timeout=300s 2>/dev/null || true

# 2. Delete the Subscription (stops OLM from reinstalling)
${KUBECTL} delete subscription hco-operatorhub -n "${CNV_NS}" --ignore-not-found 2>/dev/null || true

# 3. Delete the CSV
csv=$(${KUBECTL} get csv -n "${CNV_NS}" --no-headers 2>/dev/null \
  | awk '/kubevirt-hyperconverged/ {print $1; exit}')
if [[ -n "${csv}" ]]; then
  ${KUBECTL} delete csv "${csv}" -n "${CNV_NS}" --timeout=120s 2>/dev/null || true
fi

# 4. Delete the OperatorGroup
${KUBECTL} delete operatorgroup kubevirt-hyperconverged-group -n "${CNV_NS}" --ignore-not-found 2>/dev/null || true

# 5. Delete the namespace
${KUBECTL} delete namespace "${CNV_NS}" --ignore-not-found --timeout=300s 2>/dev/null || true

echo "==> OpenShift Virtualization removed."
