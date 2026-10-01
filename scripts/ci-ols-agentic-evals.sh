#!/bin/bash
# CI job: install lightspeed-agentic-operator, configure LLM providers,
# and run agentic troubleshooting evaluations.
#
# Input environment variables:
#   EVAL_OPENAI_API_KEY             - OpenAI API key (judge LLM + OpenAI agent)
#   EVAL_VERTEX_CREDENTIALS         - Path to GCP service account JSON (Vertex AI)
#   EVAL_VERTEX_PROJECT_ID          - GCP project ID (Vertex region is always global)
#   AGENT                           - Agent key from system-ols-agentic.yaml
#                                     (default: openai-gpt-6-luna)
#   SCENARIOS                       - Space-separated scenario list (default: all)
#   ARTIFACT_DIR                    - CI artifact directory (default: /tmp/artifacts)
#
# Scenario filtering (mutually exclusive - use one):
#   SCENARIO                        - Comma-separated scenario list (e.g., stuck_rollout,exhausted_quota)
#   TAG                             - Filter scenarios by tag (default: core)
#
# Options:
#   PREVIEW                         - Set to 1 to preview matched scenarios without running
#
# Agents and providers are read from evals/system-ols-agentic.yaml

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTIC_DIR="${REPO_DIR}/evals"
ARTIFACT_DIR="${ARTIFACT_DIR:-/tmp/artifacts}"
TAG="${TAG:-core}"

function install_operator() {
    echo "==> Installing lightspeed-agentic-operator..."
    local tmpdir
    tmpdir="$(mktemp -d)"
    git clone --depth 1 https://github.com/openshift/lightspeed-agentic-operator.git "$tmpdir"
    bash "$tmpdir/hack/quickstart/install.sh"
    rm -rf "$tmpdir"
    echo "==> Operator installed."
}

function run_evals() {
    cd "$REPO_DIR"

    # In preview mode, skip infrastructure setup and just show what would run
    if [[ "${PREVIEW:-0}" != "1" ]]; then
        # Force openshift-lightspeed namespace (override CI's auto-generated ci-op-* namespace)
        # The install.sh script respects NAMESPACE env var: NAMESPACE="${NAMESPACE:-openshift-lightspeed}"
        # Scoped to this function to avoid polluting the global environment
        local NAMESPACE=openshift-lightspeed
        export NAMESPACE

        # Step 1: Install operator (creates namespace via hack/quickstart/install.sh)
        install_operator

        # Step 2: Configure providers and create Agent CRs from system-ols-agentic.yaml
        # setup-ols-agentic.sh validates env vars and creates secrets/LLMProviders
        make setup-ols-agentic
    else
        echo "==> PREVIEW mode: skipping operator installation and provider setup"
        # Still need venv for the make target to work
        make setup-venv
    fi

    # Step 3: Run evals (all default agents from system-ols-agentic.yaml)
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
    make eval-ols-agentic "${MAKE_ARGS[@]}" || eval_status=$?

    # Collect results even if eval failed
    collect_results

    return "$eval_status"
}

function collect_results() {
    if [ ! -d "${AGENTIC_DIR}/results" ]; then
        echo "==> No results directory found, skipping collection"
        return 0
    fi

    # Find the most recently created results directory (timestamped YYYYMMDD_HHMMSS)
    local LATEST_RESULT_DIR
    LATEST_RESULT_DIR=$(find "${AGENTIC_DIR}/results" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -r | head -1)

    if [ -z "$LATEST_RESULT_DIR" ]; then
        echo "==> No results found to collect"
        return 0
    fi

    echo "==> Copying results from ${LATEST_RESULT_DIR} to ${ARTIFACT_DIR}/agentic/..."
    rm -rf "$ARTIFACT_DIR/agentic"
    mkdir -p "$ARTIFACT_DIR/agentic"
    cp -r "${AGENTIC_DIR}/results/${LATEST_RESULT_DIR}" "$ARTIFACT_DIR/agentic/" 2>/dev/null || true

    # Generate JUnit XML for Sippy ingestion
    local SUMMARY_FILES=()
    while IFS= read -r -d '' file; do
        SUMMARY_FILES+=("$file")
    done < <(find "$ARTIFACT_DIR/agentic/${LATEST_RESULT_DIR}" -name '*_summary.json' -print0 2>/dev/null | sort -z)

    if [ ${#SUMMARY_FILES[@]} -gt 0 ]; then
        echo "==> Generating JUnit XML for Sippy..."
        if [ -f "$REPO_DIR/venv/bin/python3" ]; then
            "$REPO_DIR/venv/bin/python3" "$REPO_DIR/scripts/eval-to-junit.py" \
                "$ARTIFACT_DIR/junit-agentic.xml" \
                "${SUMMARY_FILES[@]}" || echo "Warning: JUnit generation failed"
        else
            python3 "$REPO_DIR/scripts/eval-to-junit.py" \
                "$ARTIFACT_DIR/junit-agentic.xml" \
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
AGENT="${AGENT:-openai-gpt-6-luna}"
case "$AGENT" in
    openai-gpt-6-luna|openai-gpt-5-6-terra|openai-gpt-6-sol) ;;
    google-gemini-3.5-flash-lite|google-gemini-3-8-flash|google-gemini-3-7-flash) ;;
    anthropic-opus-4-6|anthropic-sonnet-5) ;;
    *)
        echo "ERROR: Unknown AGENT=${AGENT}. Valid values: openai-gpt-6-luna, openai-gpt-5-6-terra, openai-gpt-6-sol, google-gemini-3.5-flash-lite, google-gemini-3-8-flash, google-gemini-3-7-flash, anthropic-opus-4-6, anthropic-sonnet-5" >&2
        exit 1
        ;;
esac

# Only register cleanup trap if we're actually setting up the operator
if [[ "${PREVIEW:-0}" != "1" ]]; then
    trap cleanup EXIT
fi

run_evals

echo "==> Agentic evaluation complete"
