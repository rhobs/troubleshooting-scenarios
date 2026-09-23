#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --scenarios SCENARIO..."
  exit 1
}

SCENARIOS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --scenarios)
      shift
      while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do
        SCENARIOS+=("$1")
        shift
      done
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      ;;
  esac
done

[ ${#SCENARIOS[@]} -gt 0 ] || usage

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCENARIOS_DIR="$(cd "$SCRIPT_DIR/../evals/scenarios" && pwd)"

contains() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [ "$item" = "$needle" ]; then
      return 0
    fi
  done
  return 1
}

canonical_path() {
  local path="$1"
  local link_target
  local parent_dir

  # `readlink -f` is not available on macOS. Resolve the final symlink with
  # portable readlink/cd operations so remediation scenarios are only set up
  # once when their source scenario is also selected.
  while [ -L "$path" ]; do
    parent_dir="$(cd -P "$(dirname "$path")" && pwd)"
    link_target="$(readlink "$path")"
    if [[ "$link_target" = /* ]]; then
      path="$link_target"
    else
      path="$parent_dir/$link_target"
    fi
  done

  parent_dir="$(cd -P "$(dirname "$path")" && pwd)"
  printf '%s/%s\n' "$parent_dir" "$(basename "$path")"
}

group_setup_script() {
  local scenario="$1"
  local scenario_path="$SCENARIOS_DIR/$scenario"
  local group_dir

  if [[ "$scenario" != */* ]]; then
    return 0
  fi

  group_dir="$(dirname "$scenario_path")"
  if [ -x "$group_dir/setup.sh" ]; then
    printf '%s\n' "$group_dir/setup.sh"
  fi
}

for scenario in "${SCENARIOS[@]}"; do
  scenario_path="$SCENARIOS_DIR/$scenario"
  if [ ! -d "$scenario_path" ]; then
    echo "ERROR: scenario '$scenario' not found" >&2
    exit 1
  fi
done

groups_setup=()
scenario_setups=()

echo "Setting up ${#SCENARIOS[@]} scenario(s):"
printf '  %s\n' "${SCENARIOS[@]}"

for scenario in "${SCENARIOS[@]}"; do
  scenario_path="$SCENARIOS_DIR/$scenario"
  setup_script="$scenario_path/setup.sh"

  group_setup="$(group_setup_script "$scenario")"
  if [ -n "$group_setup" ]; then
    group_key="$(canonical_path "$group_setup")"
    if ! contains "$group_key" "${groups_setup[@]+"${groups_setup[@]}"}"; then
      echo ""
      echo "==> Group setup: $group_setup"
      bash "$group_setup"
      groups_setup+=("$group_key")
    fi
  fi

  if [ -x "$setup_script" ]; then
    setup_key="$(canonical_path "$setup_script")"
    if contains "$setup_key" "${scenario_setups[@]+"${scenario_setups[@]}"}"; then
      echo "==> Setup already applied for: $scenario"
      continue
    fi

    echo ""
    echo "==> Setup: $scenario"
    bash "$setup_script"
    scenario_setups+=("$setup_key")
  else
    echo ""
    echo "==> Setup: $scenario (no scenario-specific setup script)"
  fi
done

echo ""
echo "All selected scenario setups completed. No evaluations were run."
