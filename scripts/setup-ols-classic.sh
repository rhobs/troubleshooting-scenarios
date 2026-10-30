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

# shellcheck source=scripts/install-ols-operator.sh
source "$SCRIPT_DIR/install-ols-operator.sh"

existing_config="$(oc get olsconfig cluster --ignore-not-found -o name)"

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

# 6. Update Classic settings while keeping Agentic and other shared settings.
if [ -n "$existing_config" ]; then
  echo "==> Updating Classic providers and defaults in the existing OLSConfig..."
  ols_patch="$("$PYTHON" -c 'import json, sys, yaml; print(json.dumps({"spec": yaml.safe_load(sys.stdin)["spec"]}))' <<< "$ols_config")"
  oc patch olsconfig cluster --type=merge --patch="$ols_patch"
else
  echo "==> Creating OLSConfig..."
  printf '%s\n' "$ols_config" | oc apply -f -
fi

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
