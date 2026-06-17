#!/usr/bin/env bash
# Common infrastructure setup for agentic evaluations (OpenAI provider).
# Sourced by per-scenario setup scripts — do NOT run directly.
#
# Deploys: Secret, LLMProvider, Agent CRDs.
#
# Required env vars:
#   OPENAI_API_KEY   — OpenAI API key
#
# Optional env vars:
#   AGENT_MODEL      — default: gpt-5.2
#   OPERATOR_NS      — default: openshift-lightspeed

set -euo pipefail

export OPERATOR_NS="${OPERATOR_NS:-openshift-lightspeed}"
AGENT_MODEL="${AGENT_MODEL:-gpt-5.2}"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY is not set" >&2
  exit 1
fi

cat <<EOF | oc apply -n "$OPERATOR_NS" -f -
apiVersion: v1
kind: Secret
metadata:
  name: eval-llm-credentials
type: Opaque
stringData:
  OPENAI_API_KEY: ${OPENAI_API_KEY}
  LIGHTSPEED_AGENT_PROVIDER: openai
  OPENAI_MODEL: ${AGENT_MODEL}
EOF

cat <<EOF | oc apply -f -
apiVersion: agentic.openshift.io/v1alpha1
kind: LLMProvider
metadata:
  name: eval-openai
spec:
  type: OpenAI
  openAI:
    credentialsSecret:
      name: eval-llm-credentials
EOF

cat <<EOF | oc apply -f -
apiVersion: agentic.openshift.io/v1alpha1
kind: Agent
metadata:
  name: eval-default
spec:
  llmProvider:
    name: eval-openai
  model: $AGENT_MODEL
  timeouts:
    analysisSeconds: 300
    executionSeconds: 600
    verificationSeconds: 300
  maxTurns: 200
EOF

echo "Infrastructure setup complete (OpenAI, model=$AGENT_MODEL)."
