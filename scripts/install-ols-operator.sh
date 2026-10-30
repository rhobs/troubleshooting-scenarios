#!/usr/bin/env bash
# Shared OLM installation. Source this file after checking credentials.

# Skip operator installation if OLS is already installed and healthy
ols_installed=false
if oc get deployment lightspeed-app-server -n openshift-lightspeed -o name >/dev/null 2>&1; then
  if oc rollout status deployment/lightspeed-app-server -n openshift-lightspeed --timeout=10s >/dev/null 2>&1; then
    echo "OLS operator already installed and running in openshift-lightspeed"
    ols_installed=true
  fi
fi

if [ "${SKIP_OLS_INSTALL:-0}" = "1" ]; then
  echo "==> Skipping OLS operator installation (SKIP_OLS_INSTALL=1)."
elif ! $ols_installed; then
  echo "==> Installing OLS operator in openshift-lightspeed..."

  # 1. Namespace
  oc apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: openshift-lightspeed
  labels:
    openshift.io/cluster-monitoring: "true"
EOF

  # 2. OperatorGroup
  oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-lightspeed
  namespace: openshift-lightspeed
spec:
  targetNamespaces:
    - openshift-lightspeed
EOF

  # 3. Subscription
  oc apply -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: lightspeed-operator
  namespace: openshift-lightspeed
spec:
  channel: stable
  name: lightspeed-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

  # 4. Wait for operator
  echo "==> Waiting for Subscription to resolve..."
  oc wait --for=jsonpath='{.status.state}'=AtLatestKnown \
    subscription/lightspeed-operator -n openshift-lightspeed --timeout=480s

  CSV=$(oc get subscription lightspeed-operator -n openshift-lightspeed \
    -o jsonpath='{.status.currentCSV}')
  echo "==> Waiting for CSV ${CSV}..."
  oc wait --for=jsonpath='{.status.phase}'=Succeeded \
    csv/"${CSV}" -n openshift-lightspeed --timeout=480s
fi

