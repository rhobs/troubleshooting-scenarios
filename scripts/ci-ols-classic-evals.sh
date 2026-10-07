#!/bin/bash
# CI job: run OLS Classic evaluation scenarios.
#
# Agents and providers are read from the system config file (SYSTEM_CONFIG).
# The OLSConfig is built with all providers from active agents, with OpenAI as default.
#
# Input environment variables:
#   EVAL_OPENAI_API_KEY     - Required for judge LLM (always OpenAI)
#   EVAL_VERTEX_CREDENTIALS - Path to GCP service account JSON (for google/anthropic, optional)
#   EVAL_VERTEX_PROJECT_ID  - GCP project ID (auto-extracted from SA JSON if not set)
#   ARTIFACT_DIR            - CI artifact directory (default: /tmp/artifacts)
#   SYSTEM_CONFIG           - Path to system config file (default: ci-system-ols-classic.yaml for CI)
#
# Scenario filtering (mutually exclusive - use one):
#   SCENARIO                - Comma-separated scenario list (e.g., crashlooping_pod_alert,missing_configmap)
#   TAG                     - Filter scenarios by tag (default: core)
#
# Options:
#   PREVIEW                 - Set to 1 to preview matched scenarios without running
#
# Usage:
#   scripts/ci-ols-classic-evals.sh --artifact-dir "${ARTIFACT_DIR}"

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ARTIFACT_DIR:-/tmp/artifacts}"
TAG="${TAG:-core}"
SYSTEM_CONFIG="${SYSTEM_CONFIG:-${REPO_ROOT}/evals/ci-system-ols-classic.yaml}"

# Convert SYSTEM_CONFIG to absolute path if relative
if [[ "${SYSTEM_CONFIG}" != /* ]]; then
  SYSTEM_CONFIG="${REPO_ROOT}/${SYSTEM_CONFIG}"
fi

while [ $# -gt 0 ]; do
  case "$1" in
    --artifact-dir) ARTIFACT_DIR="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Create venv first (needed for PyYAML and by build-ols-classic-config.py)
make -C "$REPO_ROOT" setup-venv

# Auto-extract GCP project ID from Vertex credentials if available
if [ -n "${EVAL_VERTEX_CREDENTIALS:-}" ] && [ -f "${EVAL_VERTEX_CREDENTIALS}" ]; then
  if [ -z "${EVAL_VERTEX_PROJECT_ID:-}" ]; then
    EVAL_VERTEX_PROJECT_ID=$(python3 -c "import json; print(json.load(open('${EVAL_VERTEX_CREDENTIALS}'))['project_id'])")
    echo "==> Extracted GCP project ID: ${EVAL_VERTEX_PROJECT_ID}"
  fi
  export EVAL_VERTEX_PROJECT_ID
fi

# Extract first provider for JUnit filename (matches default provider in OLSConfig)
PROVIDER=$("${REPO_ROOT}/venv/bin/python3" -c '
import yaml
config = yaml.safe_load(open("'"${SYSTEM_CONFIG}"'"))
agents = config.get("agents", {})
default_agents = agents.get("default", {}).get("agent", [])
if default_agents:
    first_agent = default_agents[0]
    agent_config = agents.get(first_agent, {})
    provider = agent_config.get("provider", "openai")
    print(provider)
else:
    print("openai")
')

echo "==> Default provider (from first agent): ${PROVIDER}"

function run_evals() {
    cd "$REPO_ROOT"

    # In preview mode, skip OLS setup and just show what would run
    if [[ "${PREVIEW:-0}" != "1" ]]; then
        # Validate credentials before running evaluations
        : "${EVAL_OPENAI_API_KEY:?EVAL_OPENAI_API_KEY must be set (needed for judge LLM)}"

        # setup-ols-classic.sh will create OLSConfig with all providers from system config
        echo "==> Setting up OLS Classic..."
        SYSTEM_CONFIG_CLASSIC="$SYSTEM_CONFIG" make setup-ols-classic
    else
        echo "==> PREVIEW mode: skipping OLS Classic setup"
    fi

    echo "==> Running evaluations..."
    local -a MAKE_ARGS=()

    # Scenario filtering (priority: SCENARIO > TAG)
    if [[ -n "${SCENARIO:-}" ]]; then
        MAKE_ARGS+=("SCENARIO=${SCENARIO}" "TAG=")  # Clear inherited TAG to prevent double filtering
    elif [[ -n "${TAG:-}" ]]; then
        MAKE_ARGS+=("TAG=${TAG}")
    fi
    # else: no filtering, run all scenarios

    # Preview mode
    if [[ "${PREVIEW:-0}" == "1" ]]; then
        MAKE_ARGS+=("PREVIEW=1")
    fi

    # Capture eval exit status without triggering set -e
    local eval_status=0
    SYSTEM_CONFIG_CLASSIC="$SYSTEM_CONFIG" make eval-ols-classic "${MAKE_ARGS[@]}" || eval_status=$?

    # Collect results even if eval failed
    collect_results

    return "$eval_status"
}

function collect_results() {
    # Skip collection in preview mode
    if [[ "${PREVIEW:-0}" == "1" ]]; then
        # Clean up any stale JUnit XML from previous runs
        rm -f "${ARTIFACT_DIR}/junit-classic-${PROVIDER}.xml"
        return 0
    fi

    if [ -z "$ARTIFACT_DIR" ] || [ ! -d "${REPO_ROOT}/evals/results" ]; then
        return 0
    fi

    # Find the most recently created results directory (timestamped YYYYMMDD_HHMMSS)
    local LATEST_RESULT_DIR
    LATEST_RESULT_DIR=$(find "${REPO_ROOT}/evals/results" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -r | head -1)

    if [ -z "$LATEST_RESULT_DIR" ]; then
        echo "==> No results found to collect"
        return 0
    fi

    echo "==> Copying results from ${LATEST_RESULT_DIR} to ${ARTIFACT_DIR}/classic/..."
    mkdir -p "${ARTIFACT_DIR}/classic"
    cp -r "${REPO_ROOT}/evals/results/${LATEST_RESULT_DIR}" "${ARTIFACT_DIR}/classic/" 2>/dev/null || true

    # Generate JUnit XML for Sippy ingestion
    local SUMMARY_FILES=()
    while IFS= read -r -d '' file; do
        SUMMARY_FILES+=("$file")
    done < <(find "${ARTIFACT_DIR}/classic/${LATEST_RESULT_DIR}" -name '*_summary.json' -print0 2>/dev/null | sort -z)

    if [ ${#SUMMARY_FILES[@]} -gt 0 ]; then
        echo "==> Generating JUnit XML for Sippy..."
        if [ -f "${REPO_ROOT}/venv/bin/python3" ]; then
            "${REPO_ROOT}/venv/bin/python3" "${REPO_ROOT}/scripts/eval-to-junit.py" \
                "${ARTIFACT_DIR}/junit-classic-${PROVIDER}.xml" \
                "${SUMMARY_FILES[@]}" || echo "Warning: JUnit generation failed"
        else
            python3 "${REPO_ROOT}/scripts/eval-to-junit.py" \
                "${ARTIFACT_DIR}/junit-classic-${PROVIDER}.xml" \
                "${SUMMARY_FILES[@]}" || echo "Warning: JUnit generation failed"
        fi
    fi
}

function cleanup() {
    echo "==> Cleaning up OLS Classic..."
    cd "$REPO_ROOT"
    make cleanup-ols-classic || true
}

# Only register cleanup trap if we're actually setting up OLS
if [[ "${PREVIEW:-0}" != "1" ]]; then
    trap cleanup EXIT
fi

run_evals

echo "==> OLS Classic evaluation complete"
