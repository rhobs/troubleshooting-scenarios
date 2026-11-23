#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../../scripts" && pwd)/check-prerequisites.sh"

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"

echo "Creating Group..."
oc apply -f "$FIXTURE_DIR/group.yaml"

echo "Verifying Group was created..."
oc get group app-reviewers

echo "Setup complete."
