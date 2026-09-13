#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../scripts" && pwd)/check-prerequisites.sh"

command -v podman >/dev/null 2>&1 || {
  echo "ERROR: podman is required to build the gateway image" >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "ERROR: curl is required to verify gateway traffic" >&2
  exit 1
}

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
IMAGE_DIR="$(cd "$(dirname "$0")/image" && pwd)"
NS="ingress-layer"
IMAGE_TAG="${GATEWAY_PROXY_IMAGE_TAG:-release}"
REGISTRY_REPOSITORY="${GATEWAY_PROXY_REGISTRY_REPOSITORY:-${NS}/gateway-proxy}"
REGISTRY_LOCAL_PORT="${GATEWAY_PROXY_REGISTRY_LOCAL_PORT:-5000}"
PUSH_REGISTRY="localhost:${REGISTRY_LOCAL_PORT}"
LOCAL_IMAGE="gateway-proxy:${IMAGE_TAG}"
PUSH_IMAGE="${PUSH_REGISTRY}/${REGISTRY_REPOSITORY}:${IMAGE_TAG}"
CLUSTER_IMAGE="image-registry.openshift-image-registry.svc:5000/${REGISTRY_REPOSITORY}:${IMAGE_TAG}"
RENDERED_MANIFEST="$(mktemp)"
REGISTRY_PORT_FORWARD_LOG="$(mktemp)"
PORT_FORWARD_LOG="$(mktemp)"
AUTHFILE_DIR="$(mktemp -d)"
AUTHFILE="$AUTHFILE_DIR/auth.json"
REGISTRY_PORT_FORWARD_PID=""
PORT_FORWARD_PID=""

cleanup_runtime() {
  if [ -n "$PORT_FORWARD_PID" ]; then
    kill "$PORT_FORWARD_PID" 2>/dev/null || true
    wait "$PORT_FORWARD_PID" 2>/dev/null || true
  fi
  if [ -n "$REGISTRY_PORT_FORWARD_PID" ]; then
    kill "$REGISTRY_PORT_FORWARD_PID" 2>/dev/null || true
    wait "$REGISTRY_PORT_FORWARD_PID" 2>/dev/null || true
  fi
  rm -f "$RENDERED_MANIFEST" "$REGISTRY_PORT_FORWARD_LOG" "$PORT_FORWARD_LOG"
  rm -rf "$AUTHFILE_DIR"
}
trap cleanup_runtime EXIT

if oc get namespace "$NS" >/dev/null 2>&1; then
  namespace_phase="$(oc get namespace "$NS" -o jsonpath='{.status.phase}')"
  namespace_deleting="$(oc get namespace "$NS" -o jsonpath='{.metadata.deletionTimestamp}')"
  if [ "$namespace_phase" = "Terminating" ] || [ -n "$namespace_deleting" ]; then
    echo "Waiting for namespace/$NS deletion to complete..."
    for _ in $(seq 1 90); do
      if ! oc get namespace "$NS" >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
    if oc get namespace "$NS" >/dev/null 2>&1; then
      echo "ERROR: namespace/$NS is still terminating" >&2
      exit 1
    fi
  fi
fi

oc create namespace "$NS" 2>/dev/null || true

echo "Building gateway image $LOCAL_IMAGE..."
podman build --tag "$LOCAL_IMAGE" "$IMAGE_DIR"

echo "Starting registry port-forward on ${PUSH_REGISTRY}..."
oc port-forward \
  -n openshift-image-registry \
  service/image-registry \
  "${REGISTRY_LOCAL_PORT}:5000" >"$REGISTRY_PORT_FORWARD_LOG" 2>&1 &
REGISTRY_PORT_FORWARD_PID=$!

registry_ready=false
for _ in $(seq 1 30); do
  status="$(curl -k -sS -o /dev/null -w '%{http_code}' \
    --connect-timeout 2 "https://${PUSH_REGISTRY}/v2/" 2>/dev/null || true)"
  case "$status" in
    200|401|403)
      registry_ready=true
      break
      ;;
  esac
  sleep 1
done
if [ "$registry_ready" != true ]; then
  echo "ERROR: registry port-forward did not become ready" >&2
  cat "$REGISTRY_PORT_FORWARD_LOG" >&2 || true
  exit 1
fi

echo "Authenticating to registry $PUSH_REGISTRY..."
oc registry login \
  --registry="$PUSH_REGISTRY" \
  --insecure \
  --to="$AUTHFILE"

podman tag "$LOCAL_IMAGE" "$PUSH_IMAGE"
echo "Pushing gateway image to $PUSH_REGISTRY..."
podman push \
  --authfile "$AUTHFILE" \
  --tls-verify=false \
  "$PUSH_IMAGE"

sed "s|IMAGE_PLACEHOLDER|$CLUSTER_IMAGE|g" \
  "$FIXTURE_DIR/manifest.yaml" > "$RENDERED_MANIFEST"
oc apply -f "$RENDERED_MANIFEST"

for deployment in database-primary cache-primary database-shadow cache-shadow gateway-proxy; do
  echo "Waiting for deployment/$deployment..."
  oc wait --for=condition=Available "deployment/$deployment" \
    -n "$NS" --timeout=180s
done

LOCAL_PORT="${GATEWAY_PROXY_LOCAL_PORT:-18080}"
oc port-forward -n "$NS" service/gateway-proxy \
  "$LOCAL_PORT:8080" >"$PORT_FORWARD_LOG" 2>&1 &
PORT_FORWARD_PID=$!

wait_for_status() {
  local expected="$1"
  local attempts="$2"
  local status
  for _ in $(seq 1 "$attempts"); do
    status="$(curl -sS -o /dev/null -w '%{http_code}' \
      --connect-timeout 2 "http://127.0.0.1:${LOCAL_PORT}/api/health" \
      2>/dev/null || true)"
    if [ "$status" = "$expected" ]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

echo "Waiting for successful production traffic..."
if ! wait_for_status 200 60; then
  echo "ERROR: gateway did not return HTTP 200 with production configuration" >&2
  oc logs deployment/gateway-proxy -n "$NS" --tail=50 || true
  exit 1
fi

echo "Applying the alternate endpoint configuration..."
oc create configmap gateway-proxy-config \
  --from-file=app.json="$FIXTURE_DIR/config-staging.json" \
  -n "$NS" --dry-run=client -o yaml | oc apply -f -

echo "Waiting for refused upstream traffic..."
if ! wait_for_status 503 60; then
  echo "ERROR: gateway did not return HTTP 503 after configuration update" >&2
  oc logs deployment/gateway-proxy -n "$NS" --tail=100 || true
  exit 1
fi

LOGS="$(oc logs deployment/gateway-proxy -n "$NS" --tail=200)"
if ! grep -q "upstream_connect_failed" <<<"$LOGS"; then
  echo "ERROR: gateway logs did not show an upstream connection failure" >&2
  exit 1
fi
if ! grep -q "Connection refused" <<<"$LOGS"; then
  echo "ERROR: gateway logs did not show a refused connection" >&2
  exit 1
fi

echo "Setup complete: production traffic succeeded before the configuration update and real refused upstream connections now produce HTTP 503 responses."
