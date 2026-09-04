#!/bin/bash
# CI job: install lightspeed-agentic-operator, configure LLM providers,
# and run agentic troubleshooting evaluations.
#
# Input environment variables:
#   OPENAI_API_KEY                  - OpenAI API key (judge LLM + OpenAI agent)
#   GOOGLE_APPLICATION_CREDENTIALS  - Path to GCP service account JSON (Vertex AI)
#   VERTEX_PROJECT_ID               - GCP project ID (falls back to credentials JSON)
#   VERTEX_REGION                   - GCP region (default: us-east1)
#   AGENT_NAME                      - Agent to use: openai (OpenAI), gemini (Google), opus (Anthropic)
#   SCENARIOS                       - Space-separated scenario list (default: all)
#   ARTIFACT_DIR                    - CI artifact directory (default: /tmp/artifacts)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTIC_DIR="${REPO_DIR}/agentic"
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

function setup_openai() {
    echo "==> Setting up OpenAI provider..."
    : "${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"

    oc create secret generic llm-creds-openai -n "$NAMESPACE" \
        --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
        --dry-run=client -o yaml | oc apply -f -

    oc apply -f - <<'EOF'
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
---
apiVersion: agentic.openshift.io/v1alpha1
kind: Agent
metadata:
  name: default
  namespace: openshift-lightspeed
spec:
  llmProvider:
    name: openai
  model: "gpt-5.4"
  timeouts:
    analysisSeconds: 600
    executionSeconds: 600
    verificationSeconds: 600
EOF
    echo "    OpenAI provider configured."
}

function setup_vertex() {
    echo "==> Setting up Vertex AI providers..."
    : "${GOOGLE_APPLICATION_CREDENTIALS:?GOOGLE_APPLICATION_CREDENTIALS must be set}"

    if [[ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
        echo "ERROR: GCP credentials file not found at $GOOGLE_APPLICATION_CREDENTIALS" >&2
        exit 1
    fi

    if [[ -z "${VERTEX_PROJECT_ID:-}" ]]; then
        VERTEX_PROJECT_ID=$(python3 -c "import json; print(json.load(open('$GOOGLE_APPLICATION_CREDENTIALS'))['project_id'])")
        echo "    Extracted project ID from credentials: $VERTEX_PROJECT_ID"
    fi
    VERTEX_REGION="${VERTEX_REGION:-us-east1}"

    oc create secret generic llm-creds-vertex -n "$NAMESPACE" \
        --from-file=GOOGLE_APPLICATION_CREDENTIALS="$GOOGLE_APPLICATION_CREDENTIALS" \
        --dry-run=client -o yaml | oc apply -f -

    oc apply -f - <<EOF
apiVersion: agentic.openshift.io/v1alpha1
kind: LLMProvider
metadata:
  name: vertex-anthropic
  namespace: $NAMESPACE
spec:
  type: GoogleCloudVertex
  googleCloudVertex:
    projectID: $VERTEX_PROJECT_ID
    region: $VERTEX_REGION
    modelProvider: Anthropic
    credentialsSecret:
      name: llm-creds-vertex
---
apiVersion: agentic.openshift.io/v1alpha1
kind: Agent
metadata:
  name: opus
  namespace: $NAMESPACE
spec:
  llmProvider:
    name: vertex-anthropic
  model: "claude-opus-4-6"
  timeouts:
    analysisSeconds: 300
    executionSeconds: 300
    verificationSeconds: 300
---
apiVersion: agentic.openshift.io/v1alpha1
kind: LLMProvider
metadata:
  name: vertex-google
  namespace: $NAMESPACE
spec:
  type: GoogleCloudVertex
  googleCloudVertex:
    projectID: $VERTEX_PROJECT_ID
    region: global
    modelProvider: Google
    credentialsSecret:
      name: llm-creds-vertex
---
apiVersion: agentic.openshift.io/v1alpha1
kind: Agent
metadata:
  name: gemini
  namespace: $NAMESPACE
spec:
  llmProvider:
    name: vertex-google
  model: "gemini-2.5-pro"
  timeouts:
    analysisSeconds: 300
    executionSeconds: 300
    verificationSeconds: 300
EOF
    echo "    Vertex AI providers configured (Anthropic + Gemini)."
}

function run_evals() {
    echo "==> Running agentic evaluations for agent: ${AGENT_NAME}"
    cd "$AGENTIC_DIR"

    # Override system.yaml to use only the specified agent
    local AGENT_MODEL
    case "$AGENT_NAME" in
        openai) AGENT_MODEL="gpt-5.4" ;;
        gemini) AGENT_MODEL="gemini-2.5-pro" ;;
        opus) AGENT_MODEL="claude-opus-4-6" ;;
    esac

    # Backup original system.yaml
    cp system.yaml system.yaml.backup

    # Update system.yaml to use only the specified agent (no Python dependencies)
    sed -i.tmp "s/agent: \[gpt-5.4, gemini-2.5-pro, claude-opus-4-6\]/agent: [${AGENT_MODEL}]/" system.yaml
    rm -f system.yaml.tmp

    # Validate that system.yaml now contains exactly the expected agent
    if ! grep -q "agent: \[${AGENT_MODEL}\]" system.yaml; then
        echo "ERROR: Failed to configure system.yaml with agent: [${AGENT_MODEL}]"
        echo "Expected pattern not found after sed replacement."
        echo "Current agent configuration:"
        grep "agent: \[" system.yaml || echo "  (no agent: [...] line found)"
        mv system.yaml.backup system.yaml
        exit 1
    fi

    # Verify no multi-agent configuration remains
    if grep -q "agent: \[.*,.*\]" system.yaml; then
        echo "ERROR: system.yaml still contains multi-agent configuration after replacement"
        echo "Current agent configuration:"
        grep "agent: \[" system.yaml
        mv system.yaml.backup system.yaml
        exit 1
    fi

    echo "==> Verified system.yaml configured with single agent: [${AGENT_MODEL}]"

    # Run setup after system.yaml is modified
    make setup

    if [[ -n "${SCENARIOS:-}" ]]; then
        # Convert space-separated SCENARIOS to comma-separated SCENARIO for Makefile
        local SCENARIO_LIST="${SCENARIOS// /,}"
        make eval SCENARIO="$SCENARIO_LIST"
    else
        make eval
    fi

    # Restore original system.yaml
    mv system.yaml.backup system.yaml
}

function collect_results() {
    echo "==> Collecting results to ${ARTIFACT_DIR}..."
    mkdir -p "$ARTIFACT_DIR/agentic-${AGENT_NAME}"
    cp -r "$AGENTIC_DIR/results/"* "$ARTIFACT_DIR/agentic-${AGENT_NAME}/" 2>/dev/null || true
}

function cleanup() {
    echo "==> Cleaning up..."
    cd "$AGENTIC_DIR"
    # Restore system.yaml if backup exists (ensures clean workspace on all exit paths)
    if [[ -f system.yaml.backup ]]; then
        mv system.yaml.backup system.yaml
    fi
    make cleanup || true
}

trap cleanup EXIT

# Default to 'openai' if not specified
AGENT_NAME="${AGENT_NAME:-openai}"

echo "==> Running agentic evaluations for agent: ${AGENT_NAME}"

install_operator

echo "==> Configuring LLM providers..."
case "$AGENT_NAME" in
    openai)
        # OpenAI agent - always needs OpenAI for both agent and judge
        setup_openai
        ;;
    gemini)
        # Google Gemini agent - needs Vertex for agent, OpenAI for judge
        setup_openai  # For judge LLM
        setup_vertex
        ;;
    opus)
        # Anthropic Opus agent - needs Vertex for agent, OpenAI for judge
        setup_openai  # For judge LLM
        setup_vertex
        ;;
    *)
        echo "ERROR: Unknown AGENT_NAME=${AGENT_NAME}. Valid values: openai, gemini, opus"
        exit 1
        ;;
esac

run_evals
collect_results

echo "==> Agentic evaluation complete for agent: ${AGENT_NAME}"
