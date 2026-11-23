#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../../scripts" && pwd)/check-prerequisites.sh"

echo "Cleaning up scenario..."
oc delete group app-reviewers --ignore-not-found

echo "Cleanup complete."
