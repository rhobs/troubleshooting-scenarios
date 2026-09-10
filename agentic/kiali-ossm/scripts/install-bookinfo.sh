#!/usr/bin/env bash
# Install Bookinfo via Kiali hack scripts with Istio sidecar injection.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KIALI_DIR="$SCRIPT_DIR"

KUBECTL="${KUBECTL:-oc}"
NAMESPACE="${BOOKINFO_NAMESPACE:-bookinfo}"
CP_NAMESPACE="${BOOKINFO_CP_NAMESPACE:-istio-system}"
ISTIO_CR_NAME="${BOOKINFO_ISTIO_CR_NAME:-default}"
ISTIO_REVISION="${BOOKINFO_ISTIO_REVISION:-$ISTIO_CR_NAME}"
ISTIO_VERSION="${BOOKINFO_ISTIO_VERSION:-1.28.0}"
OUTPUT_DIR="${BOOKINFO_OUTPUT_DIR:-$SCRIPT_DIR/../../_output}"
KIALI_BOOKINFO_REF="${KIALI_BOOKINFO_REF:-master}"
MESH_LABELS="${BOOKINFO_MESH_LABELS:-istio-discovery=enabled}"
SCRIPT_EXTRA="${BOOKINFO_SCRIPT_EXTRA:--tg}"
TRAFFIC_ROUTE="${BOOKINFO_TRAFFIC_ROUTE:-http://productpage.$NAMESPACE.svc.cluster.local:9080/productpage}"

BOOKINFO_HACK_DIR="$OUTPUT_DIR/bookinfo-hack"
BOOKINFO_RAW_BASE="https://raw.githubusercontent.com/kiali/kiali/${KIALI_BOOKINFO_REF}/hack/istio"

# --- Fetch Kiali hack scripts ---
if [ -f "$BOOKINFO_HACK_DIR/.fetched-ref" ] && \
   [ "$(cat "$BOOKINFO_HACK_DIR/.fetched-ref")" = "$KIALI_BOOKINFO_REF" ] && \
   [ -f "$BOOKINFO_HACK_DIR/install-bookinfo-demo.sh" ] && \
   [ -f "$BOOKINFO_HACK_DIR/functions.sh" ]; then
  echo "Bookinfo hack already present ($KIALI_BOOKINFO_REF)"
else
  echo "Fetching Kiali bookinfo hack ($KIALI_BOOKINFO_REF)..."
  mkdir -p "$BOOKINFO_HACK_DIR/kustomization" "$BOOKINFO_HACK_DIR/bookinfo-traffic"
  for f in install-bookinfo-demo.sh functions.sh istio-gateway.yaml download-istio.sh; do
    curl -fsSL --connect-timeout 10 --max-time 120 "$BOOKINFO_RAW_BASE/$f" -o "$BOOKINFO_HACK_DIR/$f"
  done
  chmod a+x "$BOOKINFO_HACK_DIR/install-bookinfo-demo.sh" "$BOOKINFO_HACK_DIR/download-istio.sh"
  curl -fsSL --max-time 120 "$BOOKINFO_RAW_BASE/kustomization/bookinfo-ppc64le.yaml" -o "$BOOKINFO_HACK_DIR/kustomization/bookinfo-ppc64le.yaml"
  curl -fsSL --max-time 120 "$BOOKINFO_RAW_BASE/kustomization/bookinfo-s390x.yaml" -o "$BOOKINFO_HACK_DIR/kustomization/bookinfo-s390x.yaml"
  curl -fsSL --max-time 120 "$BOOKINFO_RAW_BASE/bookinfo-traffic/http-route-productpage-v1.yaml" -o "$BOOKINFO_HACK_DIR/bookinfo-traffic/http-route-productpage-v1.yaml"
  printf '%s\n' "$KIALI_BOOKINFO_REF" > "$BOOKINFO_HACK_DIR/.fetched-ref"
fi

# --- Download Istio release ---
ISTIO_HOME="$OUTPUT_DIR/istio-$ISTIO_VERSION"
if [ -n "${BOOKINFO_ISTIO_DIR:-}" ]; then
  echo "BOOKINFO_ISTIO_DIR set to $BOOKINFO_ISTIO_DIR; skip download"
  ISTIO_HOME="$BOOKINFO_ISTIO_DIR"
elif [ -x "$ISTIO_HOME/bin/istioctl" ]; then
  echo "Istio already present at $ISTIO_HOME"
else
  ver="${ISTIO_VERSION#v}"
  os=$(uname -s); uarch=$(uname -m)
  case "$os:$uarch" in
    Linux:x86_64) tuple=linux-amd64 ;;
    Linux:aarch64|Linux:arm64) tuple=linux-arm64 ;;
    Darwin:arm64) tuple=osx-arm64 ;;
    Darwin:x86_64) tuple=osx ;;
    *) echo "Unsupported OS/arch $os/$uarch; set BOOKINFO_ISTIO_DIR." >&2; exit 1 ;;
  esac
  base="istio-${ver}-${tuple}"
  tgz="${base}.tar.gz"
  url="https://github.com/istio/istio/releases/download/${ver}/${tgz}"
  echo "Downloading $url..."
  mkdir -p "$OUTPUT_DIR"
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  (cd "$tmp" && curl -fSL --connect-timeout 15 --max-time 300 -o "$tgz" "$url" && \
   curl -fSL --connect-timeout 15 --max-time 120 -o "$tgz.sha256" "$url.sha256")
  if command -v sha256sum >/dev/null 2>&1; then (cd "$tmp" && sha256sum -c "$tgz.sha256"); \
  elif command -v shasum >/dev/null 2>&1; then (cd "$tmp" && shasum -a 256 -c "$tgz.sha256"); \
  else echo "Need sha256sum or shasum" >&2; exit 1; fi
  (cd "$tmp" && tar -xzf "$tgz")
  rm -rf "$ISTIO_HOME"; mv "$tmp/istio-${ver}" "$ISTIO_HOME"
  trap - EXIT; rm -rf "$tmp"
  echo "Istio $ver ready at $ISTIO_HOME"
fi

# --- Install Bookinfo ---
echo "==> Bookinfo: using istio.io/rev=$ISTIO_REVISION"
OUTPUT_DIR="$OUTPUT_DIR" bash "$BOOKINFO_HACK_DIR/install-bookinfo-demo.sh" \
  -c "$KUBECTL" -n "$NAMESPACE" -in "$CP_NAMESPACE" -wt 5m -id "$ISTIO_HOME" \
  -ail "istio.io/rev=$ISTIO_REVISION" $SCRIPT_EXTRA

echo "==> Bookinfo: namespace labels ($MESH_LABELS istio.io/rev=$ISTIO_REVISION)"
$KUBECTL label namespace "$NAMESPACE" istio-injection- 2>/dev/null || true
$KUBECTL label namespace "$NAMESPACE" $MESH_LABELS "istio.io/rev=$ISTIO_REVISION" --overwrite

echo "==> Bookinfo: rollout restart for sidecar injection"
$KUBECTL rollout restart deployment --all -n "$NAMESPACE" 2>/dev/null || true
$KUBECTL rollout restart statefulset --all -n "$NAMESPACE" 2>/dev/null || true

if $KUBECTL get configmap traffic-generator-config -n "$NAMESPACE" -o name >/dev/null 2>&1; then
  patch=$(printf '%s' '[{"op":"replace","path":"/data/route","value":"'"$TRAFFIC_ROUTE"'"}]')
  $KUBECTL patch configmap traffic-generator-config -n "$NAMESPACE" --type=json -p "$patch"
  $KUBECTL delete pod -n "$NAMESPACE" -l kiali-test=traffic-generator --ignore-not-found=true --wait=false 2>/dev/null || true
  echo "==> Bookinfo: traffic generator route -> $TRAFFIC_ROUTE"
fi

# --- Validate Bookinfo health via Kiali API ---
echo "==> Kiali health check: waiting for $NAMESPACE/productpage-v1 to be Healthy..."
max_wait="${BOOKINFO_HEALTH_WAIT_SECONDS:-300}"
retry="${BOOKINFO_HEALTH_RETRY_SECONDS:-5}"
elapsed=0

kiali_host=$($KUBECTL -n "$CP_NAMESPACE" get route kiali -o jsonpath='{.spec.host}' 2>/dev/null || true)
if [ -z "$kiali_host" ]; then
  echo "Kiali route not found in namespace $CP_NAMESPACE"
  exit 1
fi

kiali_token=$($KUBECTL whoami -t 2>/dev/null || true)
if [ -z "$kiali_token" ]; then
  $KUBECTL adm policy add-cluster-role-to-user cluster-reader -z default -n "$CP_NAMESPACE" >/dev/null 2>&1 || true
  kiali_token=$($KUBECTL create token default -n "$CP_NAMESPACE" --duration=1h 2>/dev/null || true)
  if [ -z "$kiali_token" ]; then
    echo "Cannot obtain token for Kiali API auth." >&2
    exit 1
  fi
fi

api_url="https://${kiali_host}/api/clusters/workloads?health=true&istioResources=true&namespaces=${NAMESPACE}&clusterName=Kubernetes"
while true; do
  response=$(curl -ksS --max-time 20 -H "Authorization: Bearer $kiali_token" "$api_url" 2>/dev/null || true)
  status=""
  if command -v jq >/dev/null 2>&1; then
    status=$(printf '%s' "$response" | jq -r --arg ns "$NAMESPACE" --arg wl "productpage-v1" \
      '.workloads[]? | select(.namespace == $ns and .name == $wl) | .health.status.status' 2>/dev/null | head -n 1 || true)
  else
    if echo "$response" | tr -d '\n\r' | grep -Eq '"name":"productpage-v1".*"namespace":"'"$NAMESPACE"'".*"status":\{"status":"Healthy"'; then
      status="Healthy"
    fi
  fi
  if [ "$status" = "Healthy" ]; then
    echo "==> Kiali health check OK: $NAMESPACE/productpage-v1 is Healthy"
    break
  fi
  if [ "$elapsed" -ge "$max_wait" ]; then
    echo "Timed out after ${max_wait}s waiting for $NAMESPACE/productpage-v1 to be Healthy" >&2
    exit 1
  fi
  printf "."
  sleep "$retry"
  elapsed=$((elapsed + retry))
done
echo ""
echo "==> Bookinfo install complete."
