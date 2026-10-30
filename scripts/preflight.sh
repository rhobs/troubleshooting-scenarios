#!/usr/bin/env bash
set -euo pipefail

# Setup calls preflight before OLS is installed, so it uses optional mode.
MODE="optional"
SYSTEM_CONFIG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --require-ols) MODE="classic"; shift ;;
    --require-agentic) MODE="agentic"; shift ;;
    --system-config)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "ERROR: --system-config needs a file" >&2
        exit 2
      fi
      SYSTEM_CONFIG="$2"
      shift 2
      ;;
    *) echo "ERROR: unknown preflight option: $1" >&2; exit 2 ;;
  esac
done

if [ "$MODE" = "agentic" ] && [ -z "$SYSTEM_CONFIG" ]; then
  echo "ERROR: --require-agentic needs --system-config FILE" >&2
  exit 2
fi

echo "==> Preflight checks..."

# 1. oc available
if ! command -v oc >/dev/null 2>&1; then
  printf '\033[0;31mFAIL:\033[0m oc command not found\n'
  exit 1
fi
printf '\033[0;32m  OK:\033[0m oc available\n'

# 2. Logged in
if ! oc whoami >/dev/null 2>&1; then
  printf '\033[0;31mFAIL:\033[0m not logged in (oc whoami failed)\n'
  exit 1
fi
user="$(oc whoami)"
printf '\033[0;32m  OK:\033[0m logged in as %s\n' "$user"

# 3. Check tools and credentials shared by both evaluation modes.
script_dir="$(cd "$(dirname "$0")" && pwd)"
python="${script_dir}/../venv/bin/python3"
evaluator="${script_dir}/../venv/bin/lightspeed-eval"
if [ "$MODE" != "optional" ]; then
  if [ ! -x "$python" ] || [ ! -x "$evaluator" ]; then
    printf '\033[0;31mFAIL:\033[0m evaluation tools not found (run make setup-ols-%s)\n' "$MODE"
    exit 1
  fi
  printf '\033[0;32m  OK:\033[0m evaluation tools available\n'

  if [ -z "${EVAL_OPENAI_API_KEY:-}" ]; then
    printf '\033[0;31mFAIL:\033[0m EVAL_OPENAI_API_KEY not set (needed for judge LLM)\n'
    exit 1
  fi
  printf '\033[0;32m  OK:\033[0m EVAL_OPENAI_API_KEY set\n'

  if [ -n "${EVAL_VERTEX_CREDENTIALS:-}" ]; then
    printf '\033[0;32m  OK:\033[0m EVAL_VERTEX_CREDENTIALS set\n'
  fi
  if [ -n "${EVAL_VERTEX_PROJECT_ID:-}" ]; then
    printf '\033[0;32m  OK:\033[0m EVAL_VERTEX_PROJECT_ID set\n'
  fi
fi

# 4. Check the service required by this evaluation mode.
if [ "$MODE" = "agentic" ]; then
  if ! oc api-resources --api-group=agentic.openshift.io 2>/dev/null | grep -q '^agents[[:space:]]'; then
    printf '\033[0;31mFAIL:\033[0m OpenShift Lightspeed not available: run make setup-ols-agentic\n'
    exit 1
  fi
  printf '\033[0;32m  OK:\033[0m OpenShift Lightspeed is available\n'

  if ! "$python" "$script_dir/sync-agent-crs.py" --check "$SYSTEM_CONFIG"; then
    printf '\033[0;31mFAIL:\033[0m Agent CR check failed\n'
    exit 1
  fi
  printf '\033[0;32m  OK:\033[0m Agent CRs match %s\n' "$SYSTEM_CONFIG"
elif ! oc api-resources --api-group=ols.openshift.io 2>/dev/null | grep -q olsconfigs; then
  if [ "$MODE" = "classic" ]; then
    printf '\033[0;31mFAIL:\033[0m OpenShift Lightspeed not available: run make setup-ols-classic\n'
    exit 1
  fi
else
  printf '\033[0;32m  OK:\033[0m OpenShift Lightspeed is available\n'

  # Check whether the OLS Classic server is available.
  if oc get deployment lightspeed-app-server -n openshift-lightspeed -o name >/dev/null 2>&1; then
    avail="$(oc get deployment lightspeed-app-server -n openshift-lightspeed \
      -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || true)"
    if [ "$avail" = "True" ]; then
      printf '\033[0;32m  OK:\033[0m lightspeed-app-server is Available\n'
    else
      if [ "$MODE" = "classic" ]; then
        printf '\033[0;31mFAIL:\033[0m lightspeed-app-server exists but is not Available\n'
        exit 1
      fi
      printf '\033[0;33mWARN:\033[0m lightspeed-app-server exists but is not Available\n'
    fi
  else
    if [ "$MODE" = "classic" ]; then
      printf '\033[0;31mFAIL:\033[0m lightspeed-app-server deployment not found in openshift-lightspeed (run make setup-ols-classic)\n'
      exit 1
    fi
    printf '\033[0;33mWARN:\033[0m lightspeed-app-server deployment not found in openshift-lightspeed\n'
  fi
fi

echo "==> Preflight complete."
