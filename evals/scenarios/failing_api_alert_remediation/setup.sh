#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../../scripts" && pwd)/check-prerequisites.sh"

SCENARIO_DIR="$(cd "$(dirname "$0")/../../../labs/payments-api-failure" && pwd)"

make -C "$SCENARIO_DIR" deploy
make -C "$SCENARIO_DIR" break
