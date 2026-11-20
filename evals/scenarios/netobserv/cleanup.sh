#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

NETOBSERV_INSTALL_SCRIPT="$SCRIPT_DIR/scripts/install-netobserv-release.sh"
NETOBSERV_FLOWCOLLECTOR_FILE="${NETOBSERV_FLOWCOLLECTOR_FILE:-$SCRIPT_DIR/scripts/flowcollector.yaml}"
NETOBSERV_NS="${NETOBSERV_NS:-netobserv}"
NETOBSERV_OPERATOR_NS="${NETOBSERV_OPERATOR_NS:-openshift-netobserv-operator}"
KUBERNETES_CLI="${KUBERNETES_CLI:-oc}"
NETOBSERV_CATALOG_SOURCE="${NETOBSERV_CATALOG_SOURCE:-redhat}"
NETOBSERV_CHANNEL="${NETOBSERV_CHANNEL:-}"
NETOBSERV_DELETE_OPERATOR_NAMESPACE="${NETOBSERV_DELETE_OPERATOR_NAMESPACE:-yes}"

NETOBSERV_INSTALL_FLAGS=(
  -c "$KUBERNETES_CLI"
  -ns "$NETOBSERV_NS"
  -ons "$NETOBSERV_OPERATOR_NS"
  -cs "$NETOBSERV_CATALOG_SOURCE"
  -fc "$NETOBSERV_FLOWCOLLECTOR_FILE"
)
if [[ -n "$NETOBSERV_CHANNEL" ]]; then
  NETOBSERV_INSTALL_FLAGS+=( -ch "$NETOBSERV_CHANNEL" )
fi

echo "==> Removing NetObserv FlowCollector..."
bash "$NETOBSERV_INSTALL_SCRIPT" "${NETOBSERV_INSTALL_FLAGS[@]}" delete-flowcollector || true

echo "==> Removing NetObserv operator..."
if [[ "$NETOBSERV_DELETE_OPERATOR_NAMESPACE" == "yes" ]]; then
  bash "$NETOBSERV_INSTALL_SCRIPT" "${NETOBSERV_INSTALL_FLAGS[@]}" -don delete-operator || true
else
  bash "$NETOBSERV_INSTALL_SCRIPT" "${NETOBSERV_INSTALL_FLAGS[@]}" delete-operator || true
fi
