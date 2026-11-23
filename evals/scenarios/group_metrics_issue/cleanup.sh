#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../../scripts" && pwd)/check-prerequisites.sh"

GROUP_NAME="app-reviewers"
STATE_FILE="${TMPDIR:-/tmp}/troubleshooting-scenarios-group-metrics-issue-created"

if [[ -f "${STATE_FILE}" ]]; then
  echo "Cleaning up scenario-created Group..."
  oc delete group "${GROUP_NAME}" --ignore-not-found
  rm -f "${STATE_FILE}"
  echo "Cleanup complete."
else
  echo "No ownership marker found. Preserving any existing Group '${GROUP_NAME}'."
fi
