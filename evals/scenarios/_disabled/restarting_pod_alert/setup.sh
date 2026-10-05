#!/usr/bin/env bash
set -euo pipefail

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$SCENARIO_DIR/../../../../scripts" && pwd)"
# shellcheck source=scripts/scenario-namespace.sh
source "$SCRIPTS_DIR/scenario-namespace.sh"
FIXTURE_DIR="$SCENARIO_DIR/fixtures"
IMAGE_DIR="$SCENARIO_DIR/image"
VERIFY="$SCENARIO_DIR/verify_fixture.py"
NS="data-processing"
APP="report-generator"
CONTAINER="app"
REGISTRY_NAMESPACE="openshift-image-registry"
REGISTRY_SERVICE="image-registry"
REGISTRY_LOCAL_PORT="${REGISTRY_LOCAL_PORT:-5000}"
REGISTRY_ENDPOINT="127.0.0.1:${REGISTRY_LOCAL_PORT}"
PUSH_REGISTRY="$REGISTRY_ENDPOINT"
REGISTRY_PORT_FORWARD_ADDRESS="127.0.0.1"
REGISTRY_LOGIN_ARGS=()
if [ "$(uname -s)" = Darwin ]; then
  # Podman on macOS runs in a VM, so localhost is the VM, not the host.
  PUSH_REGISTRY="host.containers.internal:${REGISTRY_LOCAL_PORT}"
  REGISTRY_PORT_FORWARD_ADDRESS="0.0.0.0"
  REGISTRY_LOGIN_ARGS+=(--skip-check)
fi
REGISTRY_REPOSITORY="${NS}/report-generator"
CLUSTER_REGISTRY="image-registry.openshift-image-registry.svc:5000"
OC_REQUEST_TIMEOUT="${OC_REQUEST_TIMEOUT:-60}"
BUILD_TIMEOUT="${BUILD_TIMEOUT:-600}"
PUSH_TIMEOUT="${PUSH_TIMEOUT:-300}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-180}"
FAULT_TIMEOUT="${FAULT_TIMEOUT:-900}"
ALERT_TIMEOUT="${ALERT_TIMEOUT:-300}"

"$SCRIPTS_DIR/check-prerequisites.sh"

for command_name in podman python3 curl timeout; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: '$command_name' is required by the report-generator fixture" >&2
    exit 1
  fi
done

validate_seconds() {
  local name="$1"
  local value="$2"
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: $name must be a positive integer number of seconds" >&2
    exit 1
  fi
}

validate_port() {
  if ! [[ "$REGISTRY_LOCAL_PORT" =~ ^[1-9][0-9]*$ ]] || [ "$REGISTRY_LOCAL_PORT" -gt 65535 ]; then
    echo "ERROR: REGISTRY_LOCAL_PORT must be between 1 and 65535" >&2
    exit 1
  fi
}

validate_seconds OC_REQUEST_TIMEOUT "$OC_REQUEST_TIMEOUT"
validate_seconds BUILD_TIMEOUT "$BUILD_TIMEOUT"
validate_seconds PUSH_TIMEOUT "$PUSH_TIMEOUT"
validate_seconds ROLLOUT_TIMEOUT "$ROLLOUT_TIMEOUT"
validate_seconds FAULT_TIMEOUT "$FAULT_TIMEOUT"
validate_seconds ALERT_TIMEOUT "$ALERT_TIMEOUT"
validate_port

"$SCRIPTS_DIR/enable-uwm.sh"

umask 077
TMP_DIR="$(mktemp -d)"
AUTHFILE="$TMP_DIR/auth.json"
REGISTRY_LOG="$TMP_DIR/registry-port-forward.log"
NAMESPACE_ERROR="$TMP_DIR/namespace-check.err"
REGISTRY_PORT_FORWARD_PID=""
HEALTHY_IMAGE=""
AFFECTED_IMAGE=""

oc_request() {
  timeout --foreground "$OC_REQUEST_TIMEOUT" oc "$@"
}

print_failure_diagnostics() {
  echo "==> Bounded fixture diagnostics (namespace $NS)" >&2
  oc_request get deployment,replicaset,pod -n "$NS" -o wide 2>/dev/null | tail -n 40 >&2 || true
  oc_request logs deployment/"$APP" -n "$NS" -c "$CONTAINER" --tail=30 2>/dev/null || true
}

cleanup_runtime() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    print_failure_diagnostics
  fi
  if [ -n "$REGISTRY_PORT_FORWARD_PID" ]; then
    kill "$REGISTRY_PORT_FORWARD_PID" 2>/dev/null || true
    wait "$REGISTRY_PORT_FORWARD_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP_DIR"
  exit "$status"
}
trap cleanup_runtime EXIT

if oc_request get namespace "$NS" >/dev/null 2>"$NAMESPACE_ERROR"; then
  echo "ERROR: namespace/$NS already exists; use a fresh dedicated namespace or complete cleanup first" >&2
  exit 1
elif ! grep -qiE 'notfound|not found' "$NAMESPACE_ERROR"; then
  echo "ERROR: could not determine whether namespace/$NS is available" >&2
  cat "$NAMESPACE_ERROR" >&2
  exit 1
fi

if ! oc_request get service "$REGISTRY_SERVICE" -n "$REGISTRY_NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: OpenShift internal registry service is unavailable" >&2
  exit 1
fi

if ! python3 - "$REGISTRY_LOCAL_PORT" <<'PY'
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", int(sys.argv[1])))
PY
then
  echo "ERROR: local registry port $REGISTRY_LOCAL_PORT is already in use" >&2
  exit 1
fi

scenario_create_namespace "$NS" "$FIXTURE_DIR/namespace.yaml" oc_request

echo "Starting registry port-forward on $PUSH_REGISTRY..."
oc port-forward \
  --address "$REGISTRY_PORT_FORWARD_ADDRESS" \
  -n "$REGISTRY_NAMESPACE" \
  "service/$REGISTRY_SERVICE" \
  "${REGISTRY_LOCAL_PORT}:5000" >"$REGISTRY_LOG" 2>&1 &
REGISTRY_PORT_FORWARD_PID=$!

registry_ready=false
for _ in $(seq 1 30); do
  if ! kill -0 "$REGISTRY_PORT_FORWARD_PID" 2>/dev/null; then
    break
  fi
  status_code="$(curl -k -sS -o /dev/null -w '%{http_code}' \
    --connect-timeout 2 --max-time 5 "https://${REGISTRY_ENDPOINT}/v2/" 2>/dev/null || true)"
  case "$status_code" in
    200|401|403)
      registry_ready=true
      break
      ;;
  esac
  sleep 1
done
if [ "$registry_ready" != true ]; then
  echo "ERROR: internal registry port-forward did not become ready" >&2
  cat "$REGISTRY_LOG" >&2 || true
  exit 1
fi

echo "Authenticating to the internal registry..."
timeout --foreground "$OC_REQUEST_TIMEOUT" oc registry login \
  --registry="$PUSH_REGISTRY" \
  --insecure \
  "${REGISTRY_LOGIN_ARGS[@]}" \
  --to="$AUTHFILE"
[ -s "$AUTHFILE" ] || {
  echo "ERROR: registry authentication did not create an auth file" >&2
  exit 1
}

build_and_push() {
  local version="$1"
  local local_manifest="report-generator-multiarch:${version}"
  local destination="${PUSH_REGISTRY}/${REGISTRY_REPOSITORY}:${version}"
  local digest_file="$TMP_DIR/${version}.digest"
  local digest

  podman manifest rm "$local_manifest" >/dev/null 2>&1 ||
    podman image rm "$local_manifest" >/dev/null 2>&1 || true

  echo "Building amd64/arm64 report-generator release $version..."
  timeout --foreground "$BUILD_TIMEOUT" podman build \
    --platform linux/amd64,linux/arm64 \
    --manifest "$local_manifest" \
    --build-arg "APP_VERSION=$version" \
    "$IMAGE_DIR"

  echo "Pushing multi-architecture report-generator release $version..."
  timeout --foreground "$PUSH_TIMEOUT" podman manifest push \
    --authfile "$AUTHFILE" \
    --tls-verify=false \
    --digestfile "$digest_file" \
    --all \
    "$local_manifest" \
    "docker://$destination"

  digest="$(cat "$digest_file" 2>/dev/null || true)"
  if ! [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "ERROR: Podman did not return a valid digest for report-generator:$version" >&2
    exit 1
  fi
  if [ "$version" = "1.0.1" ]; then
    HEALTHY_IMAGE="${CLUSTER_REGISTRY}/${REGISTRY_REPOSITORY}@${digest}"
  else
    AFFECTED_IMAGE="${CLUSTER_REGISTRY}/${REGISTRY_REPOSITORY}@${digest}"
  fi
}

build_and_push "1.0.1"
build_and_push "1.0.2"

render_deployment() {
  local image="$1"
  local output="$2"
  timeout --foreground "$OC_REQUEST_TIMEOUT" oc set image --local \
    -f "$FIXTURE_DIR/manifest.yaml" \
    "$CONTAINER=$image" \
    -o yaml >"$output"
  [ -s "$output" ] || {
    echo "ERROR: rendered Deployment is empty" >&2
    exit 1
  }
  grep -Fq "kind: Deployment" "$output" || {
    echo "ERROR: rendered output is not a Deployment" >&2
    exit 1
  }
  grep -Fq "  name: $APP" "$output" || {
    echo "ERROR: rendered Deployment has the wrong name" >&2
    exit 1
  }
  grep -Fq "  namespace: $NS" "$output" || {
    echo "ERROR: rendered Deployment has the wrong namespace" >&2
    exit 1
  }
  grep -Fq "image: $image" "$output" || {
    echo "ERROR: rendered Deployment does not contain the requested image digest" >&2
    exit 1
  }
}

oc_request apply -f "$FIXTURE_DIR/prometheusrule.yaml"
render_deployment "$HEALTHY_IMAGE" "$TMP_DIR/healthy-deployment.yaml"
oc_request apply -f "$TMP_DIR/healthy-deployment.yaml"

echo "Waiting for the healthy report-generator release..."
timeout --foreground "$ROLLOUT_TIMEOUT" oc rollout status "deployment/$APP" -n "$NS" --timeout="${ROLLOUT_TIMEOUT}s"
timeout --foreground "$ROLLOUT_TIMEOUT" oc wait --for=condition=Available "deployment/$APP" -n "$NS" --timeout="${ROLLOUT_TIMEOUT}s"
timeout --foreground "$ROLLOUT_TIMEOUT" python3 "$VERIFY" healthy \
  --image "$HEALTHY_IMAGE" --duration 30 --timeout "$ROLLOUT_TIMEOUT"

echo "Rolling report-generator to the affected release..."
timeout --foreground "$OC_REQUEST_TIMEOUT" oc set image "deployment/$APP" "$CONTAINER=$AFFECTED_IMAGE" -n "$NS"
timeout --foreground "$ROLLOUT_TIMEOUT" oc rollout status "deployment/$APP" -n "$NS" --timeout="${ROLLOUT_TIMEOUT}s"
timeout --foreground "$FAULT_TIMEOUT" python3 "$VERIFY" fault \
  --image "$AFFECTED_IMAGE" --timeout "$FAULT_TIMEOUT"
timeout --foreground "$((ALERT_TIMEOUT + 5))" \
  "$SCRIPTS_DIR/wait-for-alert.sh" "DataProcessingPodRestarting" "critical" "$ALERT_TIMEOUT"

echo "Setup complete: report-generator is processing with the affected release and has produced verified OOM/restart evidence."
