#!/bin/bash
# CI job: install lightspeed-agentic-operator, configure LLM providers,
# and run agentic troubleshooting evaluations.
#
# Input environment variables:
#   OPENAI_API_KEY                  - OpenAI API key (judge LLM + OpenAI agent)
#   GOOGLE_APPLICATION_CREDENTIALS  - Path to GCP service account JSON (Vertex AI)
#   VERTEX_PROJECT_ID               - GCP project ID (falls back to credentials JSON)
#   VERTEX_REGION                   - GCP region (default: us-east1)
#   AGENT                           - Agent key from system-ols-agentic.yaml
#                                     (default: openai-gpt-5-6-luna)
#   SCENARIOS                       - Space-separated scenario list (default: all)
#   ARTIFACT_DIR                    - CI artifact directory (default: /tmp/artifacts)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTIC_DIR="${REPO_DIR}/evals"
ARTIFACT_DIR="${ARTIFACT_DIR:-/tmp/artifacts}"
NAMESPACE="openshift-lightspeed"

function install_operator() {
    echo "==> Installing lightspeed-agentic-operator..."
    local tmpdir
    tmpdir="$(mktemp -d)"
    git clone --depth 1 https://github.com/openshift/lightspeed-agentic-operator.git "$tmpdir"
    bash "$tmpdir/hack/quickstart/install.sh"
    rm -rf "$tmpdir"
    echo "==> Operator installed."
}

function setup_openai_secret() {
    echo "==> Setting up OpenAI secret for judge LLM..."
    : "${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"

    oc create secret generic llm-creds-openai -n "$NAMESPACE" \
        --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
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
      name: llm-creds-openai
EOF
    echo "    OpenAI provider configured."
}

function setup_vertex() {
    local PROVIDER_NAME="$1"
    local MODEL_PROVIDER
    echo "==> Setting up Vertex AI provider: ${PROVIDER_NAME}..."
    : "${GOOGLE_APPLICATION_CREDENTIALS:?GOOGLE_APPLICATION_CREDENTIALS must be set}"

    if [[ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
        echo "ERROR: GCP credentials file not found at $GOOGLE_APPLICATION_CREDENTIALS" >&2
        exit 1
    fi

    if [[ -z "${VERTEX_PROJECT_ID:-}" ]]; then
        VERTEX_PROJECT_ID=$(python3 -c "import json; print(json.load(open('$GOOGLE_APPLICATION_CREDENTIALS'))['project_id'])")
        echo "    Extracted project ID from credentials: $VERTEX_PROJECT_ID"
    fi

    oc create secret generic llm-creds-vertex -n "$NAMESPACE" \
        --from-file=GOOGLE_APPLICATION_CREDENTIALS="$GOOGLE_APPLICATION_CREDENTIALS" \
        --dry-run=client -o yaml | oc apply -f -

    case "$PROVIDER_NAME" in
        vertex-anthropic)
            VERTEX_REGION="${VERTEX_REGION:-us-east1}"
            MODEL_PROVIDER="Anthropic"
            ;;
        vertex-google)
            VERTEX_REGION="global"
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
    projectID: $VERTEX_PROJECT_ID
    region: $VERTEX_REGION
    modelProvider: ${MODEL_PROVIDER}
    credentialsSecret:
      name: llm-creds-vertex
EOF
    echo "    Vertex AI provider configured: ${MODEL_PROVIDER}"
}

function run_evals() {
    echo "==> Running agentic evaluations for agent: ${AGENT}"
    cd "$REPO_DIR"

    # Create Agent CRs from system-ols-agentic.yaml.
    make setup-ols-agentic

    # Run evals with AGENT variable
    local -a MAKE_ARGS=("AGENT=${AGENT}")
    if [[ -n "${SCENARIOS:-}" ]]; then
        # Convert space-separated SCENARIOS to comma-separated SCENARIO for Makefile
        local SCENARIO_LIST="${SCENARIOS// /,}"
        MAKE_ARGS+=("SCENARIO=${SCENARIO_LIST}")
    fi

    make eval-ols-agentic "${MAKE_ARGS[@]}"
}

function collect_results() {
    echo "==> Collecting results to ${ARTIFACT_DIR}..."
    mkdir -p "$ARTIFACT_DIR/agentic-${AGENT}"
    cp -r "$AGENTIC_DIR/results/"* "$ARTIFACT_DIR/agentic-${AGENT}/" 2>/dev/null || true

    # Generate JUnit XML for Sippy ingestion
    local SUMMARY_FILES=()
    while IFS= read -r -d '' file; do
        SUMMARY_FILES+=("$file")
    done < <(find "$ARTIFACT_DIR/agentic-${AGENT}" -name '*_summary.json' -print0 2>/dev/null | sort -z)

    if [ ${#SUMMARY_FILES[@]} -gt 0 ]; then
        echo "==> Generating JUnit XML for Sippy..."
        if [ -f "$REPO_DIR/venv/bin/python3" ]; then
            "$REPO_DIR/venv/bin/python3" "$REPO_DIR/scripts/eval-to-junit.py" \
                "$ARTIFACT_DIR/junit-agentic-${AGENT}.xml" \
                "${SUMMARY_FILES[@]}" || echo "Warning: JUnit generation failed"
        else
            python3 "$REPO_DIR/scripts/eval-to-junit.py" \
                "$ARTIFACT_DIR/junit-agentic-${AGENT}.xml" \
                "${SUMMARY_FILES[@]}" || echo "Warning: JUnit generation failed"
        fi
    fi
}

function cleanup() {
    echo "==> Cleaning up..."
    cd "$REPO_DIR"
    make cleanup-ols-agentic || true
}

# Use the same agent keys as system-ols-agentic.yaml.
AGENT="${AGENT:-openai-gpt-5-6-luna}"
case "$AGENT" in
    openai-gpt-5-6-luna|openai-gpt-5-6-terra) PROVIDER_NAME="openai" ;;
    google-gemini-3.5-flash-lite|google-gemini-3-8-flash|google-gemini-3-7-flash) PROVIDER_NAME="vertex-google" ;;
    anthropic-opus-4-6|anthropic-sonnet-5) PROVIDER_NAME="vertex-anthropic" ;;
    *)
        echo "ERROR: Unknown AGENT=${AGENT}. Valid values: openai-gpt-5-6-luna, openai-gpt-5-6-terra, google-gemini-3.5-flash-lite, google-gemini-3-8-flash, google-gemini-3-7-flash, anthropic-opus-4-6, anthropic-sonnet-5" >&2
        exit 1
        ;;
esac

trap cleanup EXIT

echo "==> Running agentic evaluations for agent: ${AGENT}"

install_operator

echo "==> Configuring LLM providers..."
setup_openai_secret
case "$PROVIDER_NAME" in
    openai)
        setup_openai_provider
        ;;
    vertex-google|vertex-anthropic)
        setup_vertex "$PROVIDER_NAME"
        ;;
esac

run_evals
collect_results

echo "==> Agentic evaluation complete for agent: ${AGENT}"
