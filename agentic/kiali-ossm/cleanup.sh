#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/../../scripts" && pwd)"

OLS_NS="${OLS_NS:-openshift-lightspeed}"
MCP_NS="${MCP_NS:-openshift-mcp}"
MCP_DEPLOYMENT="${MCP_DEPLOYMENT:-openshift-mcp-server}"

OSSM_INSTALL_SCRIPT="$SCRIPT_DIR/scripts/install-ossm-release.sh"

echo "==> Disconnecting OLS from MCP server..."
OLS_NS="$OLS_NS" bash "$SCRIPTS_DIR/disconnect-ols-mcp.sh" || true

echo "==> Removing MCP server..."
MCP_NS="$MCP_NS" MCP_DEPLOYMENT="$MCP_DEPLOYMENT" \
  bash "$SCRIPTS_DIR/cleanup-mcp.sh" || true

echo "==> Removing Bookinfo namespace..."
oc delete namespace bookinfo --ignore-not-found=true || true
oc wait --for=delete namespace/bookinfo --timeout=180s 2>/dev/null || true

echo "==> Removing mesh resources (Istio/Kiali/addons CRs)..."
OSSM_DELETE_CONFIRM=yes bash "$OSSM_INSTALL_SCRIPT" -c oc -cpn istio-system delete-istio || true

echo "==> Removing OSSM Console namespace..."
oc delete namespace ossmconsole --ignore-not-found=true || true
oc wait --for=delete namespace/ossmconsole --timeout=180s 2>/dev/null || true

echo "==> Removing control-plane namespaces..."
for ns in istio-system istio-cni; do
  oc delete namespace "$ns" --ignore-not-found=true || true
  oc wait --for=delete "namespace/$ns" --timeout=180s 2>/dev/null || true
done

echo "==> Removing Sail/Kiali operators..."
OSSM_DELETE_CONFIRM=yes bash "$OSSM_INSTALL_SCRIPT" -c oc -cpn istio-system delete-operators || true

echo "==> Final residual cleanup..."
oc delete subscription --ignore-not-found=true -n openshift-operators my-kiali my-sailoperator || true
oc -n istio-system delete route --ignore-not-found=true kiali istio-ingressgateway || true
oc delete scc istio-addons-scc --ignore-not-found=true 2>/dev/null || true
