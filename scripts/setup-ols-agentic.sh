#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-${SCRIPT_DIR}/../venv}"
PYTHON="${VENV_DIR}/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "ERROR: Evaluation venv not found. Run make setup-venv first." >&2
  exit 1
fi
SYSTEM_CONFIG_AGENTIC="${SYSTEM_CONFIG_AGENTIC:-${SCRIPT_DIR}/../evals/system-ols-agentic.yaml}"
providers="$("$PYTHON" "$SCRIPT_DIR/sync-agent-crs.py" "$SYSTEM_CONFIG_AGENTIC" --list-providers)"

has_gcp=false
while IFS= read -r provider; do
  case "$provider" in
    openai)
      if [ -z "${EVAL_OPENAI_API_KEY:-}" ]; then
        echo "ERROR: EVAL_OPENAI_API_KEY is needed for OpenAI agents or judges" >&2
        exit 1
      fi
      ;;
    "") ;;
    vertex-google|vertex-anthropic) has_gcp=true ;;
    *)
      echo "ERROR: Unsupported agent provider: $provider" >&2
      exit 1
      ;;
  esac
done <<< "$providers"

if $has_gcp; then
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

NAMESPACE="openshift-lightspeed"

# shellcheck source=scripts/install-ols-operator.sh
source "$SCRIPT_DIR/install-ols-operator.sh"

agentic_deployment="lightspeed-agentic-operator-controller-manager"
full_operator="installed"
if [ "${SKIP_OLS_INSTALL:-0}" = "1" ]; then
    full_operator="$(oc get deployment lightspeed-operator-controller-manager \
        -n "$NAMESPACE" --ignore-not-found -o name)"
fi

if [ -z "$full_operator" ]; then
    echo "==> Using the existing Agentic quickstart operator and sandbox configuration."
    agentic_deployment="lightspeed-agentic-operator"
else
    if ! oc explain olsconfig.spec.agenticOLS --api-version=ols.openshift.io/v1alpha1 >/dev/null; then
        echo "ERROR: OLSConfig with Agentic support is required. Install OLS 2.0 or newer." >&2
        exit 1
    fi
    oc rollout status deployment/lightspeed-operator-controller-manager -n "$NAMESPACE" --timeout=480s

    existing_config="$(oc get olsconfig cluster --ignore-not-found -o name)"
    if [ -n "$existing_config" ]; then
        echo "==> Using existing OLSConfig; keeping Classic providers and other settings."
    else
        echo "==> Creating OLSConfig for Agentic..."
        oc apply -f - <<EOF
apiVersion: ols.openshift.io/v1alpha1
kind: OLSConfig
metadata:
  name: cluster
spec:
  llm:
    providers: []
  ols:
    defaultModel: ""
    defaultProvider: ""
  agenticOLS:
    sandboxMode: bare-pod
EOF
    fi
fi

# Wait for each CRD separately: oc can fail early when several are missing.
for crd in agents.agentic.openshift.io llmproviders.agentic.openshift.io; do
    if ! oc wait --for=create "crd/$crd" --timeout=480s || \
        ! oc wait --for=condition=Established "crd/$crd" --timeout=480s; then
        echo "ERROR: Agentic CRD $crd is not ready. Check OLS operator logs and cluster support." >&2
        exit 1
    fi
done

echo "==> Waiting for the Agentic operator and sandbox configuration..."
oc rollout status "deployment/$agentic_deployment" -n "$NAMESPACE" --timeout=480s
oc wait --for=create configmap/lightspeed-agentic-configuration -n "$NAMESPACE" --timeout=480s
oc wait --for=jsonpath='{.data.sandbox-pod-spec}' \
    configmap/lightspeed-agentic-configuration -n "$NAMESPACE" --timeout=480s

function setup_openai_secret() {
    echo "==> Setting up OpenAI secret for the agent..."
    : "${EVAL_OPENAI_API_KEY:?EVAL_OPENAI_API_KEY must be set}"

    oc create secret generic creds-agentic-openai -n "$NAMESPACE" \
        --from-literal=OPENAI_API_KEY="$EVAL_OPENAI_API_KEY" \
        --dry-run=client -o yaml | oc apply -f -

    echo "    OpenAI secret configured."
}

function setup_openai_provider() {
    echo "==> Setting up OpenAI provider..."

    oc apply -f - <<EOF
apiVersion: agentic.openshift.io/v1alpha1
kind: LLMProvider
metadata:
  name: openai
  namespace: openshift-lightspeed
spec:
  type: OpenAI
  openAI:
    credentialsSecret:
      name: creds-agentic-openai
EOF
    echo "    OpenAI provider configured."
}

function setup_vertex() {
    local PROVIDER_NAME="$1"
    local MODEL_PROVIDER
    echo "==> Setting up Vertex AI provider: ${PROVIDER_NAME}..."
    oc create secret generic creds-agentic-vertex -n "$NAMESPACE" \
        --from-file=GOOGLE_APPLICATION_CREDENTIALS="$EVAL_VERTEX_CREDENTIALS" \
        --dry-run=client -o yaml | oc apply -f -

    case "$PROVIDER_NAME" in
        vertex-anthropic)
            MODEL_PROVIDER="Anthropic"
            ;;
        vertex-google)
            MODEL_PROVIDER="Google"
            ;;
        *)
            echo "ERROR: Unknown Vertex provider: ${PROVIDER_NAME}"
            exit 1
            ;;
    esac

    oc apply -f - <<EOF
apiVersion: agentic.openshift.io/v1alpha1
kind: LLMProvider
metadata:
  name: ${PROVIDER_NAME}
  namespace: $NAMESPACE
spec:
  type: GoogleCloudVertex
  googleCloudVertex:
    projectID: $EVAL_VERTEX_PROJECT_ID
    region: global
    modelProvider: ${MODEL_PROVIDER}
    credentialsSecret:
      name: creds-agentic-vertex
EOF
    echo "    Vertex AI provider configured: ${MODEL_PROVIDER}"
}

while IFS= read -r provider; do
    case "$provider" in
        openai)
            setup_openai_secret
            setup_openai_provider
            ;;
        vertex-google|vertex-anthropic) setup_vertex "$provider" ;;
    esac
done <<< "$providers"
