#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_NS="netobserv-eval-tcp-rtt"
export TARGET_NS
export REQUIRED_NETOBSERV_FEATURES="FlowRTT"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/check_prereqs.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/wait_for.sh"

check_netobserv_prereqs
deploy_netobserv_fixture "${SCRIPT_DIR}/fixtures" "${TARGET_NS}"

wait_for_rollout "${TARGET_NS}" "slow-http-server" "180s"
wait_for_rollout "${TARGET_NS}" "rtt-client" "180s"
wait_for_log_pattern "${TARGET_NS}" "app=rtt-client" "OK round-trip|elevated RTT" 60 3
wait_for_netobserv_warmup
echo "Scenario tcp_rtt ready (TARGET_NS=${TARGET_NS})"
