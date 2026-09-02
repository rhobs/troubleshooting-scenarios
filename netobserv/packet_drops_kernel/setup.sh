#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_NS="netobserv-eval-drops-kernel"
export TARGET_NS
export REQUIRED_NETOBSERV_FEATURES="PacketDrop"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/check_prereqs.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/wait_for.sh"

check_netobserv_prereqs
deploy_netobserv_fixture "${SCRIPT_DIR}/fixtures" "${TARGET_NS}"

wait_for_rollout "${TARGET_NS}" "iperf-server" "180s"
wait_for_rollout "${TARGET_NS}" "iperf-udp-flood" "180s"
wait_for_log_pattern "${TARGET_NS}" "app=iperf-udp-flood" 'Connecting to host|Mbits/sec|Lost/Total Datagrams|[0-9]+/[0-9]+ \([0-9.]+%\)' 50 5
wait_for_netobserv_warmup
echo "Scenario packet_drops_kernel ready (TARGET_NS=${TARGET_NS})"
