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

  # `readlink -f` is not available on macOS. Resolve links with portable
  # readlink/cd operations so shared cleanup scripts run only once.
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

group_cleanup_script() {
  local scenario="$1"
  local scenario_path="$SCENARIOS_DIR/$scenario"
  local group_dir

  if [[ "$scenario" != */* ]]; then
    return 0
  fi

  group_dir="$(dirname "$scenario_path")"
  if [ -x "$group_dir/cleanup.sh" ]; then
    printf '%s\n' "$group_dir/cleanup.sh"
  fi
}

for scenario in "${SCENARIOS[@]}"; do
  scenario_path="$SCENARIOS_DIR/$scenario"
  if [ ! -d "$scenario_path" ]; then
    echo "ERROR: scenario '$scenario' not found" >&2
    exit 1
  fi
done

scenario_cleanup_keys=()
group_cleanups=()
group_cleanup_keys=()
status=0

echo "Cleaning up ${#SCENARIOS[@]} scenario(s):"
printf '  %s\n' "${SCENARIOS[@]}"

for scenario in "${SCENARIOS[@]}"; do
  scenario_path="$SCENARIOS_DIR/$scenario"
  cleanup_script="$scenario_path/cleanup.sh"

  group_cleanup="$(group_cleanup_script "$scenario")"
  if [ -n "$group_cleanup" ]; then
    group_key="$(canonical_path "$group_cleanup")"
    if ! contains "$group_key" "${group_cleanup_keys[@]+"${group_cleanup_keys[@]}"}"; then
      group_cleanups+=("$group_cleanup")
      group_cleanup_keys+=("$group_key")
    fi
  fi

  if [ -x "$cleanup_script" ]; then
    cleanup_key="$(canonical_path "$cleanup_script")"
    if contains "$cleanup_key" "${scenario_cleanup_keys[@]+"${scenario_cleanup_keys[@]}"}"; then
      echo "==> Cleanup already applied for: $scenario"
      continue
    fi

    echo ""
    echo "==> Cleanup: $scenario"
    if bash "$cleanup_script"; then
      scenario_cleanup_keys+=("$cleanup_key")
    else
      echo "ERROR: cleanup failed for $scenario" >&2
      scenario_cleanup_keys+=("$cleanup_key")
      status=1
    fi
  else
    echo ""
    echo "==> Cleanup: $scenario (no scenario-specific cleanup script)"
  fi
done

# Group cleanup removes shared infrastructure, so run it after all scenario
# cleanups. Reverse group order to unwind the shared setup sequence.
for ((index = ${#group_cleanups[@]} - 1; index >= 0; index--)); do
  group_cleanup="${group_cleanups[$index]}"
  echo ""
  echo "==> Group cleanup: $group_cleanup"
  if ! bash "$group_cleanup"; then
    echo "ERROR: group cleanup failed for $group_cleanup" >&2
    status=1
  fi
done

if [ "$status" -ne 0 ]; then
  exit "$status"
fi

echo ""
echo "All selected scenario cleanups completed."
