#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/../../scripts" && pwd)"

MCP_TOOLSETS="${MCP_TOOLSETS:-core,config,ossm}"
MCP_KIALI_URL="${MCP_KIALI_URL:-https://kiali.istio-system:20001/}"
MCP_NS="${MCP_NS:-openshift-mcp}"
MCP_DEPLOYMENT="${MCP_DEPLOYMENT:-openshift-mcp-server}"
MCP_OLS_NAME="${MCP_OLS_NAME:-openshift-mcp}"
OLS_NS="${OLS_NS:-openshift-lightspeed}"

OSSM_INSTALL_SCRIPT="$SCRIPT_DIR/scripts/install-ossm-release.sh"

echo "==> Installing OSSM operators (Sail, Kiali)..."
bash "$OSSM_INSTALL_SCRIPT" -c oc install-operators

echo "==> Installing Istio, addons, and Kiali CR..."
bash "$OSSM_INSTALL_SCRIPT" -c oc -cpn istio-system install-istio

echo "==> Waiting for Kiali deployment..."
timeout=600
elapsed=0
while ! oc get deployment/kiali -n istio-system -o name >/dev/null 2>&1; do
  if [ "$elapsed" -ge "$timeout" ]; then
    echo "Timeout (${timeout}s) waiting for deployment/kiali in istio-system" >&2
    exit 1
  fi
  echo " ... waiting for deployment/kiali ($elapsed/${timeout}s)"
  sleep 5
  elapsed=$((elapsed + 5))
done
oc rollout status deployment/kiali -n istio-system --timeout=600s
if oc get pod -n istio-system -l 'app.kubernetes.io/name=kiali' -o name >/dev/null 2>&1; then
  oc wait --for=condition=Ready pod -l 'app.kubernetes.io/name=kiali' -n istio-system --timeout=300s
elif oc get pod -n istio-system -l 'app=kiali' -o name >/dev/null 2>&1; then
  oc wait --for=condition=Ready pod -l 'app=kiali' -n istio-system --timeout=300s
fi

echo "==> Installing Kiali support..."
bash "$OSSM_INSTALL_SCRIPT" -c oc install-kiali-support

echo "==> Installing Bookinfo..."
bash "$SCRIPT_DIR/scripts/install-bookinfo.sh"

echo "==> Deploying MCP server (toolsets: ${MCP_TOOLSETS})..."
MCP_NS="$MCP_NS" MCP_DEPLOYMENT="$MCP_DEPLOYMENT" MCP_TOOLSETS="$MCP_TOOLSETS" \
  MCP_KIALI_URL="$MCP_KIALI_URL" \
  bash "$SCRIPTS_DIR/setup-mcp.sh"

echo "==> Connecting OLS to MCP server..."
MCP_NS="$MCP_NS" MCP_DEPLOYMENT="$MCP_DEPLOYMENT" MCP_OLS_NAME="$MCP_OLS_NAME" \
  OLS_NS="$OLS_NS" \
  bash "$SCRIPTS_DIR/connect-ols-mcp.sh"
