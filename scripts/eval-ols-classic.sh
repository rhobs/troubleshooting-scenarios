#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --system-config FILE [--setup-mode run|scenario|skip] --scenarios SCENARIO... [--tags TAG...]"
  exit 1
}

SYSTEM_CONFIG=""
SETUP_MODE="scenario"
SCENARIOS=()
TAGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --system-config) SYSTEM_CONFIG="$2"; shift 2 ;;
    --setup-mode)    SETUP_MODE="$2"; shift 2 ;;
    --scenarios)     shift; while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do SCENARIOS+=("$1"); shift; done ;;
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
  if [ ! -f "$scenario/evals-ols-classic.yaml" ]; then
    echo "ERROR: $scenario/evals-ols-classic.yaml not found" >&2
    exit 1
  fi
done

bash "$SCRIPT_DIR/preflight.sh" --require-ols

DATETIME="$(date +%Y%m%d_%H%M%S)"
EVAL_DIR="results/${DATETIME}"
mkdir -p "$EVAL_DIR"
cp "$SYSTEM_CONFIG" "$EVAL_DIR/system-ols-classic.yaml"
SYSTEM_CONFIG="$EVAL_DIR/system-ols-classic.yaml"

PARALLEL_RUNS="$("$PYTHON" -c "import yaml; c=yaml.safe_load(open('$SYSTEM_CONFIG')); print('yes' if c.get('agents',{}).get('default',{}).get('parallel',False) else 'no')")"
if [ "$SETUP_MODE" = "run" ]; then PARALLEL_RUNS=no; fi

TAG_FLAGS=()
if [ ${#TAGS[@]} -gt 0 ]; then
  TAG_FLAGS=(--tags "${TAGS[@]}")
fi

read -ra AGENTS <<< "$("$PYTHON" -c "import yaml; c=yaml.safe_load(open('$SYSTEM_CONFIG')); print(' '.join(c.get('agents',{}).get('default',{}).get('agent',[])))")"
REPEAT="$("$PYTHON" -c "import yaml; c=yaml.safe_load(open('$SYSTEM_CONFIG')); print(c.get('agents',{}).get('default',{}).get('repeat',1))")"

bash "$SCRIPT_DIR/show-eval-summary.sh" \
  --python "$PYTHON" \
  --system-config "$SYSTEM_CONFIG" \
  --setup-mode "$SETUP_MODE" \
  --scenarios "${SCENARIOS[@]}"

pf_pid=""
eval_sa="ols-classic-eval"
eval_sa_created=0
eval_role_bound=0

# Invoked indirectly by the EXIT trap below.
# shellcheck disable=SC2329
cleanup_ols_classic() {
  if [ -n "$pf_pid" ]; then kill "$pf_pid" 2>/dev/null || true; fi
  if [ "$eval_role_bound" -eq 1 ]; then
    oc adm policy remove-cluster-role-from-user cluster-reader -z "$eval_sa" -n openshift-lightspeed >/dev/null 2>&1 || true
  fi
  if [ "$eval_sa_created" -eq 1 ]; then
    oc delete serviceaccount "$eval_sa" -n openshift-lightspeed --ignore-not-found >/dev/null 2>&1 || true
  fi
}
trap cleanup_ols_classic EXIT

if ! curl -ksf --connect-timeout 2 "https://localhost:8443/docs" >/dev/null 2>&1; then
  echo "==> Starting port-forward to OLS..."
  oc port-forward -n openshift-lightspeed deployment/lightspeed-app-server 8443:8443 >/dev/null 2>&1 &
  pf_pid=$!
  ols_ok=false
  for _ in $(seq 1 30); do
    if curl -ksf --connect-timeout 2 "https://localhost:8443/docs" >/dev/null 2>&1; then ols_ok=true; break; fi
    sleep 2
  done
  if [ "$ols_ok" != "true" ]; then
    echo "ERROR: OLS not reachable at https://localhost:8443 after port-forward attempt" >&2
    exit 1
  fi
fi

auth_token=$(oc whoami -t 2>/dev/null || true)
if [ -z "$auth_token" ]; then
  echo "==> No OAuth token, creating service account token..."
  if ! oc get serviceaccount "$eval_sa" -n openshift-lightspeed >/dev/null 2>&1; then
    oc create serviceaccount "$eval_sa" -n openshift-lightspeed >/dev/null
    eval_sa_created=1
  fi
  if ! oc get clusterrolebinding -o jsonpath='{range .items[*]}{.roleRef.name}{"|"}{range .subjects[*]}{.kind}:{.namespace}:{.name}{" "}{end}{"\n"}{end}' 2>/dev/null \
      | grep -q "^cluster-reader|.*ServiceAccount:openshift-lightspeed:${eval_sa}"; then
    oc adm policy add-cluster-role-to-user cluster-reader -z "$eval_sa" -n openshift-lightspeed >/dev/null
    eval_role_bound=1
  fi
  auth_token=$(oc create token "$eval_sa" -n openshift-lightspeed --duration=1h)
fi

export API_KEY="$auth_token"

group_setup_script() {
  local scenario="$1"
  local group_dir
  group_dir="$(dirname "$scenario")"
  if [[ "$scenario" == */* ]] && [ -x "$group_dir/setup.sh" ]; then
    echo "$group_dir/setup.sh"
  fi
}

group_cleanup_script() {
  local scenario="$1"
  local group_dir
  group_dir="$(dirname "$scenario")"
  if [[ "$scenario" == */* ]] && [ -x "$group_dir/cleanup.sh" ]; then
    echo "$group_dir/cleanup.sh"
  fi
}

restart_port_forward() {
  if [ -n "$pf_pid" ]; then
    kill "$pf_pid" 2>/dev/null || true
    wait "$pf_pid" 2>/dev/null || true
    echo "==> Restarting port-forward after group setup..."
    oc port-forward -n openshift-lightspeed deployment/lightspeed-app-server 8443:8443 >/dev/null 2>&1 &
    pf_pid=$!
  fi
  echo "==> Waiting for OLS to be ready..."
  local ols_ok=false
  for _ in $(seq 1 30); do
    if curl -ksf --connect-timeout 2 "https://localhost:8443/docs" >/dev/null 2>&1; then ols_ok=true; break; fi
    sleep 2
  done
  if [ "$ols_ok" != "true" ]; then
    echo "ERROR: OLS not reachable after group setup" >&2
    return 1
  fi
}

overall_status=0
groups_setup=()
failed_groups=()
failed_runs=()

record_failure() {
  local status="$1"
  local label="$2"

  if [ "$overall_status" -eq 0 ]; then overall_status="$status"; fi
  failed_runs+=("$label")
  echo "WARNING: $label failed (exit $status); continuing." >&2
}

run_scenario() {
  local scenario="$1"
  local progress="$2"
  shift 2
  local scenario_status=0
  local scenario_state_dir=""

  echo ""
  echo "==> $progress"
  if [ "$SETUP_MODE" != "skip" ]; then
    echo "==> Setup: $scenario"
    scenario_state_dir="$(mktemp -d "$(cd "$EVAL_DIR" && pwd)/.scenario-state.XXXXXX")" || return $?
    if [ -x "$scenario/setup.sh" ]; then
      SCENARIO_STATE_DIR="$scenario_state_dir" bash "$scenario/setup.sh" || scenario_status=$?
    fi
  else
    echo "==> Setup skipped: $scenario (SETUP_MODE=skip)"
  fi
  if [ "$scenario_status" -eq 0 ]; then
    bash "$SCRIPT_DIR/run-agentic-evals.sh" \
      --system-config "$SYSTEM_CONFIG" \
      --evals "$scenario/evals-ols-classic.yaml" \
      --eval-dir "$EVAL_DIR" \
      "$@" \
      "${TAG_FLAGS[@]}" || scenario_status=$?
  fi
  if [ "$SETUP_MODE" != "skip" ]; then
    echo "==> Cleanup: $scenario"
    if [ -x "$scenario/cleanup.sh" ]; then
      SCENARIO_STATE_DIR="$scenario_state_dir" bash "$scenario/cleanup.sh" || echo "WARNING: cleanup failed (non-fatal)"
    fi
    # Keep ownership records if cleanup failed, so it can be retried safely.
    if ! rmdir "$scenario_state_dir" 2>/dev/null; then
      echo "==> Namespace ownership records: $scenario_state_dir"
    fi
  else
    echo "==> Cleanup skipped: $scenario (SETUP_MODE=skip)"
  fi
  return "$scenario_status"
}

total_scenarios=${#SCENARIOS[@]}
if [ "$SETUP_MODE" = "run" ]; then
  total_runs=$(( total_scenarios * ${#AGENTS[@]} * REPEAT ))
fi
scenario_index=0
for scenario in "${SCENARIOS[@]}"; do
  scenario_index=$((scenario_index + 1))
  grp_setup="$(group_setup_script "$scenario")"
  if [ -n "$grp_setup" ] && [ "$SETUP_MODE" != "skip" ]; then
    already_done=false
    group_failed=false
    for g in "${groups_setup[@]+"${groups_setup[@]}"}"; do
      if [ "$g" = "$grp_setup" ]; then already_done=true; break; fi
    done
    for g in "${failed_groups[@]+"${failed_groups[@]}"}"; do
      if [ "$g" = "$grp_setup" ]; then group_failed=true; break; fi
    done
    if [ "$group_failed" = "true" ]; then
      echo "WARNING: Skipping $scenario because group setup failed: $grp_setup" >&2
      continue
    fi
    if [ "$already_done" = "false" ]; then
      echo ""
      echo "==> Group setup: $grp_setup"
      if bash "$grp_setup"; then
        if restart_port_forward; then
          groups_setup+=("$grp_setup")
        else
          status=$?
          failed_groups+=("$grp_setup")
          record_failure "$status" "$scenario (group setup: $grp_setup)"
          continue
        fi
      else
        status=$?
        failed_groups+=("$grp_setup")
        record_failure "$status" "$scenario (group setup: $grp_setup)"
        continue
      fi
    fi
  elif [ -n "$grp_setup" ]; then
    echo "==> Group setup skipped: $grp_setup (SETUP_MODE=skip)"
  fi

  if [ "$SETUP_MODE" = "run" ]; then
    agent_index=0
    for agent in "${AGENTS[@]}"; do
      agent_index=$((agent_index + 1))
      for run in $(seq 1 "$REPEAT"); do
        progress_index=$(( (scenario_index - 1) * ${#AGENTS[@]} * REPEAT + (agent_index - 1) * REPEAT + run ))
        run_scenario "$scenario" \
          "Progress: run $progress_index/$total_runs | ${scenario#scenarios/} | agent=$agent | repeat=$run/$REPEAT" \
          --agent "$agent" \
          --run-index "$run" || record_failure "$?" "$scenario (agent=$agent run=$run)"
      done
    done
  else
    run_scenario "$scenario" \
      "Scenario $scenario_index/$total_scenarios" \
      || record_failure "$?" "$scenario"
  fi
done

if [ "$SETUP_MODE" != "skip" ]; then
  groups_cleanup=()
  for scenario in "${SCENARIOS[@]}"; do
    grp_cleanup="$(group_cleanup_script "$scenario")"
    if [ -n "$grp_cleanup" ]; then
      already_done=false
      for g in "${groups_cleanup[@]+"${groups_cleanup[@]}"}"; do
        if [ "$g" = "$grp_cleanup" ]; then already_done=true; break; fi
      done
      if [ "$already_done" = "false" ]; then
        echo "==> Group cleanup: $grp_cleanup"
        bash "$grp_cleanup" || echo "WARNING: group cleanup failed (non-fatal)"
        groups_cleanup+=("$grp_cleanup")
      fi
    fi
  done
else
  echo "==> Group cleanup skipped (SETUP_MODE=skip)"
fi

if [ ${#failed_runs[@]} -gt 0 ]; then
  echo "==> Failed scenario runs (${#failed_runs[@]}):"
  printf '  %s\n' "${failed_runs[@]}"
fi

echo ""
echo "==> Generating report..."
report_status=0
"$PYTHON" "$SCRIPT_DIR/generate-report-classic.py" \
  --parallel-runs "$PARALLEL_RUNS" \
  "$EVAL_DIR" \
  --output "$EVAL_DIR/report.md" || report_status=$?
if [ "$report_status" -eq 0 ]; then
  echo "==> Report: $EVAL_DIR/report.md"
else
  echo "ERROR: Report generation failed (exit $report_status)" >&2
  if [ "$overall_status" -eq 0 ]; then overall_status=$report_status; fi
fi

exit "$overall_status"
