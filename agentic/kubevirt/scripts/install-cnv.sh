#!/usr/bin/env bash
# Install the OpenShift Virtualization operator if not already present.
# Idempotent: skips installation if the CSV already exists and is Succeeded.
set -euo pipefail

CNV_NS="${CNV_NS:-openshift-cnv}"
KUBECTL="${KUBECTL:-oc}"
CNV_CHANNEL="${CNV_CHANNEL:-stable}"
CNV_SOURCE="${CNV_SOURCE:-redhat-operators}"
CNV_SOURCE_NS="${CNV_SOURCE_NS:-openshift-marketplace}"

echo "==> Installing OpenShift Virtualization operator..."

existing_csv=$(${KUBECTL} get csv -n "${CNV_NS}" --no-headers 2>/dev/null \
  | awk '/kubevirt-hyperconverged/ {print $1; exit}')
if [[ -n "${existing_csv}" ]]; then
  phase=$(${KUBECTL} get csv "${existing_csv}" -n "${CNV_NS}" -o jsonpath='{.status.phase}' 2>/dev/null || true)
  hco_available=$(${KUBECTL} get hyperconverged kubevirt-hyperconverged -n "${CNV_NS}" \
    -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || true)
  if [[ "${phase}" == "Succeeded" && "${hco_available}" == "True" ]]; then
    echo "==> CNV already installed (${existing_csv}). Skipping."
    exit 0
  fi
fi

${KUBECTL} create namespace "${CNV_NS}" --dry-run=client -o yaml | ${KUBECTL} apply -f -

cat <<EOF | ${KUBECTL} apply -f -
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: kubevirt-hyperconverged-group
  namespace: ${CNV_NS}
spec:
  targetNamespaces:
    - ${CNV_NS}
EOF

cat <<EOF | ${KUBECTL} apply -f -
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: hco-operatorhub
  namespace: ${CNV_NS}
spec:
  source: ${CNV_SOURCE}
  sourceNamespace: ${CNV_SOURCE_NS}
  name: kubevirt-hyperconverged
  channel: ${CNV_CHANNEL}
  installPlanApproval: Automatic
EOF

echo "==> Waiting for CNV CSV to appear..."
for _ in $(seq 1 60); do
  csv=$(${KUBECTL} get csv -n "${CNV_NS}" --no-headers 2>/dev/null \
    | awk '/kubevirt-hyperconverged/ {print $1; exit}')
  if [[ -n "${csv}" ]]; then
    break
  fi
  sleep 10
done

if [[ -z "${csv}" ]]; then
  echo "ERROR: Timed out waiting for CNV CSV to appear."
  exit 1
fi

echo "==> Waiting for CSV ${csv} to succeed..."
${KUBECTL} wait --for=jsonpath='{.status.phase}'=Succeeded csv/"${csv}" \
  -n "${CNV_NS}" --timeout=600s

echo "==> Creating HyperConverged CR..."
cat <<EOF | ${KUBECTL} apply -f -
apiVersion: hco.kubevirt.io/v1beta1
kind: HyperConverged
metadata:
  name: kubevirt-hyperconverged
  namespace: ${CNV_NS}
spec: {}
EOF

echo "==> Waiting for HyperConverged to become Available..."
for _ in $(seq 1 60); do
  status=$(${KUBECTL} get hyperconverged kubevirt-hyperconverged -n "${CNV_NS}" \
    -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || true)
  if [[ "${status}" == "True" ]]; then
    echo "==> OpenShift Virtualization installed and available."
    exit 0
  fi
  sleep 10
done

echo "ERROR: Timed out waiting for HyperConverged CR to become Available."
exit 1
