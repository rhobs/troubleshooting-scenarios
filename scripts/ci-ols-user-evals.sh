#!/bin/bash
# CI job: run OLS Classic evaluation scenarios for a specific LLM provider.
#
# Input environment variables:
#   TAG or EVAL_SUITES      - Space-separated scenario tags to run (default: kiali-ossm kubevirt netobserv)
#                             Each tag maps to a group of scenarios under evals/scenarios/
#                             TAG is preferred; EVAL_SUITES is legacy name for backward compatibility
#   OPENAI_API_KEY          - Required for judge LLM (always OpenAI)
#   OLS_DEFAULT_PROVIDER    - LLM provider: openai, google, or anthropic (default: openai)
#   OLS_DEFAULT_MODEL       - Model override (optional, has defaults per provider)
#   GCP_SERVICE_ACCOUNT_JSON - Path to GCP service account JSON (for google/anthropic)
#   GCP_PROJECT_ID          - GCP project ID (auto-extracted from SA JSON if not set)
#
# Usage:
#   scripts/ci-ols-user-evals.sh --artifact-dir "${ARTIFACT_DIR}"

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --artifact-dir) ARTIFACT_DIR="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ── Validate inputs ──────────────────────────────────────────────────

: "${OPENAI_API_KEY:?OPENAI_API_KEY must be set (needed for judge LLM)}"

# Default to all three scenario tags if not specified
# These tags map to scenario groups under evals/scenarios/
# Support both EVAL_SUITES (legacy) and TAG (new) variable names
TAGS="${TAG:-${EVAL_SUITES:-kiali-ossm kubevirt netobserv}}"

# ── Auto-extract GCP project ID from SA JSON if needed ───────────────

if [ -n "${GCP_SERVICE_ACCOUNT_JSON:-}" ] && [ -f "${GCP_SERVICE_ACCOUNT_JSON}" ] && [ -z "${GCP_PROJECT_ID:-}" ]; then
  if command -v jq &>/dev/null; then
    GCP_PROJECT_ID="$(jq -r '.project_id // empty' "$GCP_SERVICE_ACCOUNT_JSON")"
  elif command -v python3 &>/dev/null; then
    GCP_PROJECT_ID="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('project_id',''))" "$GCP_SERVICE_ACCOUNT_JSON")"
  fi
  if [ -n "$GCP_PROJECT_ID" ]; then
    export GCP_PROJECT_ID
    echo "==> Auto-detected GCP_PROJECT_ID: ${GCP_PROJECT_ID}"
  fi
fi

# ── Determine provider and model for result tracking ─────────────────

PROVIDER="${OLS_DEFAULT_PROVIDER:-openai}"
if [ -z "${OLS_DEFAULT_MODEL:-}" ]; then
  case "$PROVIDER" in
    openai)    MODEL="gpt-5.4" ;;
    google)    MODEL="gemini-2.5-pro" ;;
    anthropic) MODEL="claude-opus-4-6" ;;
    *)         MODEL="" ;;
  esac
else
  MODEL="${OLS_DEFAULT_MODEL}"
fi

echo "==> Provider: ${PROVIDER}"
echo "==> Model: ${MODEL}"
echo "==> Scenario Tags: ${TAGS}"

# ── Run evaluations for each tag ─────────────────────────────────────

run_tag() {
  local TAG="$1"

  echo ""
  echo "=========================================="
  echo "Running eval: TAG=${TAG}, PROVIDER=${PROVIDER}"
  echo "=========================================="

  cd "$REPO_ROOT"

  # For non-openai providers, hide OPENAI_API_KEY during setup so setup-ols.sh
  # only creates the GCP provider(s) in OLSConfig, avoiding multi-provider issues.
  local SAVED_OPENAI_KEY="$OPENAI_API_KEY"
  if [ "$PROVIDER" != "openai" ]; then
    echo "==> Unsetting OPENAI_API_KEY during setup (provider: ${PROVIDER})"
    unset OPENAI_API_KEY
  fi

  echo "==> Setting up OLS Classic..."
  if ! make setup-ols-classic; then
    echo "ERROR: make setup-ols-classic failed for TAG=${TAG}"
    echo "==> Running cleanup..."
    make cleanup-ols-classic || true
    export OPENAI_API_KEY="$SAVED_OPENAI_KEY"
    return 1
  fi

  # Restore OPENAI_API_KEY for the judge LLM
  export OPENAI_API_KEY="$SAVED_OPENAI_KEY"

  echo "==> Running evaluations for TAG=${TAG}..."
  local -a EVAL_ARGS=("TAG=${TAG}")
  [ -n "$MODEL" ] && EVAL_ARGS+=("MODEL=${MODEL}")

  # Run evals and capture exit status
  local EVAL_STATUS=0
  if ! make eval-ols-classic "${EVAL_ARGS[@]}"; then
    echo "ERROR: make eval-ols-classic failed for TAG=${TAG}"
    EVAL_STATUS=1
  fi

  # Collect artifacts (even if evals failed, there may be partial results)
  if [ -n "$ARTIFACT_DIR" ] && [ -d "${REPO_ROOT}/evals/results" ]; then
    # Find the most recently created results directory (timestamped YYYYMMDD_HHMMSS)
    local LATEST_RESULT_DIR
    LATEST_RESULT_DIR=$(find "${REPO_ROOT}/evals/results" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -r | head -1)

    if [ -n "$LATEST_RESULT_DIR" ]; then
      echo "==> Copying results from ${LATEST_RESULT_DIR} to ${ARTIFACT_DIR}/${TAG}/..."
      mkdir -p "${ARTIFACT_DIR}/${TAG}"
      cp -r "${REPO_ROOT}/evals/results/${LATEST_RESULT_DIR}" "${ARTIFACT_DIR}/${TAG}/" 2>/dev/null || true

      # Generate JUnit XML for Sippy ingestion
      local SUMMARY_FILES=()
      while IFS= read -r -d '' file; do
        SUMMARY_FILES+=("$file")
      done < <(find "${ARTIFACT_DIR}/${TAG}/${LATEST_RESULT_DIR}" -name '*_summary.json' -print0 2>/dev/null | sort -z)

      if [ ${#SUMMARY_FILES[@]} -gt 0 ]; then
        echo "==> Generating JUnit XML for Sippy..."
        if [ -f "${REPO_ROOT}/venv/bin/python3" ]; then
          "${REPO_ROOT}/venv/bin/python3" "${REPO_ROOT}/scripts/eval-to-junit.py" \
            "${ARTIFACT_DIR}/junit-${TAG}-${PROVIDER}.xml" \
            "${SUMMARY_FILES[@]}" || echo "Warning: JUnit generation failed"
        else
          python3 "${REPO_ROOT}/scripts/eval-to-junit.py" \
            "${ARTIFACT_DIR}/junit-${TAG}-${PROVIDER}.xml" \
            "${SUMMARY_FILES[@]}" || echo "Warning: JUnit generation failed"
        fi
      fi
    fi
  fi

  # Cleanup OLS
  echo "==> Cleaning up OLS Classic..."
  make cleanup-ols-classic || true

  # Return the evaluation status
  if [ $EVAL_STATUS -ne 0 ]; then
    echo "==> OLS evaluation failed for TAG=${TAG} / ${PROVIDER}"
    return 1
  fi

  echo "==> OLS evaluation complete for TAG=${TAG} / ${PROVIDER}"
}

# Run each tag and track results
FAILED_TAGS=()
PASSED_TAGS=()

for TAG in $TAGS; do
  if run_tag "$TAG"; then
    PASSED_TAGS+=("$TAG")
  else
    echo "ERROR: Evaluation failed for TAG=${TAG}, PROVIDER=${PROVIDER}"
    FAILED_TAGS+=("$TAG")
  fi
done

echo ""
echo "=========================================="
echo "OLS Evaluation Summary for ${PROVIDER}"
echo "=========================================="
echo "Passed (${#PASSED_TAGS[@]}): ${PASSED_TAGS[*]:-none}"
echo "Failed (${#FAILED_TAGS[@]}): ${FAILED_TAGS[*]:-none}"
echo ""

if [ ${#FAILED_TAGS[@]} -gt 0 ]; then
  echo "ERROR: ${#FAILED_TAGS[@]} tag(s) failed"
  exit 1
fi

echo "==> All OLS evaluations complete for provider: ${PROVIDER}"
