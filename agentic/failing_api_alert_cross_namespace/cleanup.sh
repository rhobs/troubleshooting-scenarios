#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../scripts" && pwd)/check-prerequisites.sh"

SCENARIO_DIR="$(cd "$(dirname "$0")/../../generic/01-payments-api-failure" && pwd)"

make -C "$SCENARIO_DIR" cleanup
