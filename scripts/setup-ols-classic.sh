#!/usr/bin/env bash
set -euo pipefail

# The evaluator always uses OpenAI for the judge, even when OLS uses another provider.
if [ -z "${EVAL_OPENAI_API_KEY:-}" ]; then
  printf '\033[0;31mERROR:\033[0m EVAL_OPENAI_API_KEY not set (needed for judge LLM)\n'
  exit 1
fi

has_gcp=false

if [ -n "${EVAL_VERTEX_CREDENTIALS:-}" ] || [ -n "${EVAL_VERTEX_PROJECT_ID:-}" ]; then
  if [ ! -f "${EVAL_VERTEX_CREDENTIALS:-}" ]; then
    echo "ERROR: EVAL_VERTEX_CREDENTIALS must point to an existing file" >&2
    exit 1
  fi
  if [ -z "${EVAL_VERTEX_PROJECT_ID:-}" ]; then
    echo "ERROR: EVAL_VERTEX_PROJECT_ID must be set with EVAL_VERTEX_CREDENTIALS" >&2
    exit 1
  fi
  has_gcp=true
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-${SCRIPT_DIR}/../venv}"
PYTHON="${VENV_DIR}/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "ERROR: Evaluation venv not found. Run make setup-venv first." >&2
  exit 1
fi

# Use SYSTEM_CONFIG_CLASSIC from environment or default to system-ols-classic.yaml
SYSTEM_CONFIG_CLASSIC="${SYSTEM_CONFIG_CLASSIC:-${SCRIPT_DIR}/../evals/system-ols-classic.yaml}"

ols_config="$("$PYTHON" "$SCRIPT_DIR/build-ols-classic-config.py" \
  "$SYSTEM_CONFIG_CLASSIC")"

# Skip operator installation if OLS is already installed and healthy
ols_installed=false
if oc get deployment lightspeed-app-server -n openshift-lightspeed -o name >/dev/null 2>&1; then
  if oc rollout status deployment/lightspeed-app-server -n openshift-lightspeed --timeout=10s >/dev/null 2>&1; then
    echo "OLS operator already installed and running in openshift-lightspeed"
    ols_installed=true
  fi
fi

if ! $ols_installed; then
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

# 5. LLM credentials
echo "==> Creating credentials secrets..."
oc create secret generic creds-classic-openai \
  --namespace openshift-lightspeed \
  --from-literal=apitoken="${EVAL_OPENAI_API_KEY}" \
  --type=Opaque \
  --dry-run=client -o yaml | oc apply -f -
if $has_gcp; then
  oc create secret generic creds-classic-vertex-google \
    --namespace openshift-lightspeed \
    --from-file=apitoken="${EVAL_VERTEX_CREDENTIALS}" \
    --type=Opaque \
    --dry-run=client -o yaml | oc apply -f -
  oc create secret generic creds-classic-vertex-anthropic \
    --namespace openshift-lightspeed \
    --from-file=apitoken="${EVAL_VERTEX_CREDENTIALS}" \
    --type=Opaque \
    --dry-run=client -o yaml | oc apply -f -
fi

# 6. Apply OLSConfig with the default model and providers from the active agents
echo "==> Applying OLSConfig..."
printf '%s\n' "$ols_config" | oc apply -f -

# 7. Wait for OLS to be ready
if ! $ols_installed; then
  echo "==> Waiting for lightspeed-app-server deployment to appear..."
  elapsed=0
  while ! oc get deployment lightspeed-app-server -n openshift-lightspeed -o name >/dev/null 2>&1; do
    if [ "$elapsed" -ge 480 ]; then
      echo "ERROR: lightspeed-app-server not created after 480s"
      exit 1
    fi
    echo "  ... waiting for lightspeed-app-server (${elapsed}/480s)"
    sleep 5
    elapsed=$((elapsed + 5))
  done
fi
echo "==> Waiting for rollout..."
oc rollout status deployment/lightspeed-app-server -n openshift-lightspeed --timeout=480s
echo "==> OLS installed and ready in openshift-lightspeed."
