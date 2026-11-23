#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../../scripts" && pwd)/check-prerequisites.sh"

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
GROUP_NAME="app-reviewers"
STATE_FILE="${TMPDIR:-/tmp}/troubleshooting-scenarios-group-metrics-issue-created"

# Remove stale ownership marker
rm -f "${STATE_FILE}"

# Check if Group already exists
if oc get group "${GROUP_NAME}" >/dev/null 2>&1; then
  echo "ERROR: Group '${GROUP_NAME}' already exists. Refusing to modify it."
  echo "Delete it manually if you own it, or choose a different Group name."
  exit 1
fi

# Record ownership before creation
: > "${STATE_FILE}"

echo "Creating Group..."
if ! oc apply -f "$FIXTURE_DIR/group.yaml"; then
  rm -f "${STATE_FILE}"  # Clean up marker on failure
  exit 1
fi

echo "Verifying Group was created..."
oc get group "${GROUP_NAME}"

echo "Setup complete."
