#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_NS="netobserv-eval-drops-policy"
export TARGET_NS
# OVS_DROP_EXPLICIT in flows needs PacketDrop; NetpolDenied metric needs NetworkEvents.
export REQUIRED_NETOBSERV_FEATURES="NetworkEvents PacketDrop"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/check_prereqs.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/wait_for.sh"

check_netobserv_prereqs
deploy_netobserv_fixture "${SCRIPT_DIR}/fixtures" "${TARGET_NS}"

wait_for_rollout "${TARGET_NS}" "policy-backend" "180s"
wait_for_rollout "${TARGET_NS}" "policy-frontend" "180s"
# Probe every ~5s — need several blocked attempts before NetObserv/Loki show OVS drops.
wait_for_min_log_matches "${TARGET_NS}" "app=policy-frontend" "connection blocked|timed out" 5 60 5
wait_for_netobserv_warmup
echo "Scenario packet_drops_policy ready (TARGET_NS=${TARGET_NS})"
