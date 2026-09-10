#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/../../scripts" && pwd)"

MCP_TOOLSETS="${MCP_TOOLSETS:-core,config,kubevirt}"
MCP_NS="${MCP_NS:-openshift-mcp}"
MCP_DEPLOYMENT="${MCP_DEPLOYMENT:-openshift-mcp-server}"
MCP_OLS_NAME="${MCP_OLS_NAME:-openshift-mcp}"
OLS_NS="${OLS_NS:-openshift-lightspeed}"

echo "==> Installing OpenShift Virtualization..."
bash "$SCRIPT_DIR/scripts/install-cnv.sh"
bash "$SCRIPT_DIR/scripts/check-cnv.sh"

echo "==> Deploying MCP server (toolsets: ${MCP_TOOLSETS})..."
MCP_NS="$MCP_NS" MCP_DEPLOYMENT="$MCP_DEPLOYMENT" MCP_TOOLSETS="$MCP_TOOLSETS" \
  bash "$SCRIPTS_DIR/setup-mcp.sh"

echo "==> Connecting OLS to MCP server..."
MCP_NS="$MCP_NS" MCP_DEPLOYMENT="$MCP_DEPLOYMENT" MCP_OLS_NAME="$MCP_OLS_NAME" \
  OLS_NS="$OLS_NS" \
  bash "$SCRIPTS_DIR/connect-ols-mcp.sh"
