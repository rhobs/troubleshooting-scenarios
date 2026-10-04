#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --system-config FILE [--setup-mode run|scenario|skip] [--agents AGENT...] [--tags TAG...] --scenarios SCENARIO..."
  exit 1
}

SYSTEM_CONFIG=""
SCENARIOS=()
AGENTS=()
SETUP_MODE="scenario"
TAGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --system-config) SYSTEM_CONFIG="$2"; shift 2 ;;
    --setup-mode)    SETUP_MODE="$2"; shift 2 ;;
    --scenarios)     shift; while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do SCENARIOS+=("$1"); shift; done ;;
    --agents)        shift; while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do AGENTS+=("$1"); shift; done ;;
    --tags)          shift; while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do TAGS+=("$1"); shift; done ;;
    *) echo "Unknown arg: $1"; usage ;;
  esac
done

[ -n "$SYSTEM_CONFIG" ] && [ ${#SCENARIOS[@]} -gt 0 ] || usage
if [ "$SETUP_MODE" != "run" ] && [ "$SETUP_MODE" != "scenario" ] && [ "$SETUP_MODE" != "skip" ]; then
  echo "ERROR: setup mode must be run, scenario, or skip: $SETUP_MODE" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/../venv"
PYTHON="${VENV_DIR}/bin/python3"

for scenario in "${SCENARIOS[@]}"; do
  if [ ! -d "$scenario" ]; then
    scenario_name="${scenario##*/}"
    echo "ERROR: scenario '$scenario_name' not found. Available scenarios:" >&2
    echo ""
    available_scenarios=()
    for d in scenarios/*/; do
      scenario_name="${d%/}"
      if [ -f "${d}evals-ols-agentic.yaml" ]; then
        available_scenarios+=("${scenario_name##*/}")
      fi
    done

    if command -v column >/dev/null 2>&1; then
      terminal_width="${COLUMNS:-}"
      if ! [[ "$terminal_width" =~ ^[1-9][0-9]*$ ]]; then
        terminal_width="$(tput cols 2>/dev/null || true)"
      fi
      if [[ "$terminal_width" =~ ^[1-9][0-9]*$ ]]; then
        printf '%s\n' "${available_scenarios[@]}" |
          column -x -c "$terminal_width" | expand | sed 's/^/  /'
      else
        printf '  %s\n' "${available_scenarios[@]}"
      fi
    else
      printf '  %s\n' "${available_scenarios[@]}"
    fi
    exit 64
  fi
done

bash "$SCRIPT_DIR/preflight.sh" --require-agentic --system-config "$SYSTEM_CONFIG"

DATETIME="$(date +%Y%m%d_%H%M%S)"
EVAL_DIR="results/${DATETIME}"
mkdir -p "$EVAL_DIR"
cp "$SYSTEM_CONFIG" "$EVAL_DIR/system-ols-agentic.yaml"
SYSTEM_CONFIG="$EVAL_DIR/system-ols-agentic.yaml"

if [ ${#AGENTS[@]} -eq 0 ]; then
  read -ra AGENTS <<< "$("$PYTHON" -c "import yaml; c=yaml.safe_load(open('$SYSTEM_CONFIG')); print(' '.join(c.get('agents',{}).get('default',{}).get('agent',[])))")"
fi

REPEAT="$("$PYTHON" -c "import yaml; c=yaml.safe_load(open('$SYSTEM_CONFIG')); print(c.get('agents',{}).get('default',{}).get('repeat',1))")"

PARALLEL_RUNS="$("$PYTHON" -c "import yaml; c=yaml.safe_load(open('$SYSTEM_CONFIG')); print('yes' if c.get('agents',{}).get('default',{}).get('parallel',False) else 'no')")"
if [ "$SETUP_MODE" = "run" ]; then PARALLEL_RUNS=no; fi

TAG_FLAGS=()
if [ ${#TAGS[@]} -gt 0 ]; then
  TAG_FLAGS=(--tags "${TAGS[@]}")
fi

SUMMARY_AGENT_ARGS=()
if [ ${#AGENTS[@]} -gt 0 ]; then
  SUMMARY_AGENT_ARGS=(--agents "${AGENTS[@]}")
fi
bash "$SCRIPT_DIR/show-eval-summary.sh" \
  --python "$PYTHON" \
  --system-config "$SYSTEM_CONFIG" \
  --setup-mode "$SETUP_MODE" \
  "${SUMMARY_AGENT_ARGS[@]}" \
  --scenarios "${SCENARIOS[@]}"

# shellcheck source=scripts/eval-report.sh
source "$SCRIPT_DIR/eval-report.sh"

# Invoked by the EXIT trap.
# shellcheck disable=SC2329
finish_evaluation() {
  local status=$?
  local report_status=0
  trap - EXIT INT TERM
  report_finalize "$status" || report_status=$?
  if [ "$report_status" -ne 0 ]; then
    echo "ERROR: final report update failed; keeping the last report." >&2
    if [ "$status" -eq 0 ]; then status=$report_status; fi
  fi
  exit "$status"
}

report_init agentic
trap finish_evaluation EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

run_scenario() {
  local scenario="$1"
  local progress="$2"
  local report_output="$3"
  shift 3
  local scenario_status=0
  local scenario_state_dir=""
  local failure_detail=""

  report_event start quiet "$scenario" "$@"

  echo ""
  echo "==> $progress"
  if [ "$SETUP_MODE" != "skip" ]; then
    echo "==> Setup: $scenario"
    scenario_state_dir="$(mktemp -d "$(cd "$EVAL_DIR" && pwd)/.scenario-state.XXXXXX")" || scenario_status=$?
    if [ "$scenario_status" -eq 0 ] && [ -x "$scenario/setup.sh" ]; then
      SCENARIO_STATE_DIR="$scenario_state_dir" bash "$scenario/setup.sh" || scenario_status=$?
    fi
    if [ "$scenario_status" -ne 0 ]; then failure_detail="Setup failed (exit $scenario_status)"; fi
  else
    echo "==> Setup skipped: $scenario (SETUP_MODE=skip)"
  fi
  if [ "$scenario_status" -eq 0 ]; then
    bash "$SCRIPT_DIR/run-agentic-evals.sh" \
      --system-config "$SYSTEM_CONFIG" \
      --evals "$scenario/evals-ols-agentic.yaml" \
      --eval-dir "$EVAL_DIR" \
      "$@" \
      "${TAG_FLAGS[@]}" || scenario_status=$?
    if [ "$scenario_status" -ne 0 ]; then failure_detail="Evaluation failed (exit $scenario_status)"; fi
  fi
  if [ "$SETUP_MODE" != "skip" ] && [ -n "$scenario_state_dir" ]; then
    echo "==> Cleanup: $scenario"
    if [ -x "$scenario/cleanup.sh" ]; then
      SCENARIO_STATE_DIR="$scenario_state_dir" bash "$scenario/cleanup.sh" || echo "WARNING: cleanup failed (non-fatal)"
    fi
    # Keep ownership records if cleanup failed, so it can be retried safely.
    if ! rmdir "$scenario_state_dir" 2>/dev/null; then
      echo "==> Namespace ownership records: $scenario_state_dir"
    fi
  elif [ "$SETUP_MODE" = "skip" ]; then
    echo "==> Cleanup skipped: $scenario (SETUP_MODE=skip)"
  fi
  report_event finish "$report_output" "$scenario" "$@" --exit-code "$scenario_status" --detail "$failure_detail"
  return "$scenario_status"
}

overall_status=0
failed_runs=()

record_failure() {
  local status="$1"
  local label="$2"

  if [ "$overall_status" -eq 0 ]; then overall_status="$status"; fi
  failed_runs+=("$label")
  echo "WARNING: $label failed (exit $status); continuing." >&2
}

if [ "$SETUP_MODE" = "run" ]; then
  total_runs=$(( ${#SCENARIOS[@]} * ${#AGENTS[@]} * REPEAT ))
  progress_index=0
  for scenario in "${SCENARIOS[@]}"; do
    for agent in "${AGENTS[@]}"; do
      for run in $(seq 1 "$REPEAT"); do
        progress_index=$((progress_index + 1))
        report_output=quiet
        if [ "$agent" = "${AGENTS[-1]}" ] && [ "$run" -eq "$REPEAT" ]; then
          report_output=table
        fi
        run_scenario "$scenario" \
          "Progress: run $progress_index/$total_runs | ${scenario#scenarios/} | agent=$agent | repeat=$run/$REPEAT" \
          "$report_output" \
          --agent "$agent" \
          --run-index "$run" || record_failure "$?" "$scenario (agent=$agent run=$run)"
      done
    done
  done
else
  total_scenarios=${#SCENARIOS[@]}
  progress_index=0
  for scenario in "${SCENARIOS[@]}"; do
    progress_index=$((progress_index + 1))
    run_scenario "$scenario" \
      "Scenario $progress_index/$total_scenarios" table \
      || record_failure "$?" "$scenario"
  done
fi

if [ ${#failed_runs[@]} -gt 0 ]; then
  echo "==> Failed scenario runs (${#failed_runs[@]}):"
  printf '  %s\n' "${failed_runs[@]}"
fi

REPORT_FINISHED=1
exit "$overall_status"
