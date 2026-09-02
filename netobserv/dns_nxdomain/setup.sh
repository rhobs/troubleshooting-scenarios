#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_NS="netobserv-eval-dns-nxdomain"
export TARGET_NS
export REQUIRED_NETOBSERV_FEATURES="DNSTracking"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/check_prereqs.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/wait_for.sh"

check_netobserv_prereqs
deploy_netobserv_fixture "${SCRIPT_DIR}/fixtures" "${TARGET_NS}"

wait_for_rollout "${TARGET_NS}" "dns-nxdomain-prober" "180s"
wait_for_log_pattern "${TARGET_NS}" "app=dns-nxdomain-prober" "NXDOMAIN|can't find|can't resolve|server can't find|SERVFAIL|not found" 60 3
wait_for_netobserv_warmup
echo "Scenario dns_nxdomain ready (TARGET_NS=${TARGET_NS})"
