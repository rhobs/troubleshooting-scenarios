#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")/../../../scripts" && pwd)"
"$SCRIPTS_DIR/check-prerequisites.sh"

GROUP_NAME="app-reviewers"
SCENARIO_STATE_DIR="${SCENARIO_STATE_DIR:-$(cd "$SCRIPTS_DIR/../evals" && pwd)/results/.scenario-state}"
STATE_FILE="$SCENARIO_STATE_DIR/${GROUP_NAME}.group"

if [[ -f "$STATE_FILE" ]]; then
  echo "Cleaning up scenario-created Group..."
  oc delete group "$GROUP_NAME" --ignore-not-found
  rm -f "$STATE_FILE"
  echo "Cleanup complete."
else
  echo "No ownership marker found. Preserving any existing Group '$GROUP_NAME'."
fi
