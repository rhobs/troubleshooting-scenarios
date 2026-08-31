#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_NS="netobserv-eval-tls"
TLS_SECRET_NAME="tls-server-cert"
TLS_CN="tls-server.netobserv-eval-tls.svc.cluster.local"
export TARGET_NS

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/check_prereqs.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../build/scripts/wait_for.sh"

check_netobserv_prereqs

if ! command -v openssl >/dev/null 2>&1; then
  echo "ERROR: openssl is required to generate the eval TLS certificate"
  exit 1
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout "${TMPDIR}/tls.key" -out "${TMPDIR}/tls.crt" \
  -subj "/CN=${TLS_CN}" 2>/dev/null

oc create secret tls "${TLS_SECRET_NAME}" \
  --cert="${TMPDIR}/tls.crt" --key="${TMPDIR}/tls.key" \
  -n "${TARGET_NS}" --dry-run=client -o yaml >"${TMPDIR}/secret.yaml"

if [[ "${NETOBSERV_EVAL_RECREATE_NS:-true}" == "true" ]] && oc get namespace "${TARGET_NS}" >/dev/null 2>&1; then
  echo "Recreating eval namespace ${TARGET_NS} for a clean fixture deploy…"
  oc delete namespace "${TARGET_NS}" --ignore-not-found --wait=false
  wait_for_namespace_gone "${TARGET_NS}" || true
fi

oc apply -f "${SCRIPT_DIR}/fixtures/manifest.yaml" -f "${TMPDIR}/secret.yaml"

for _ in $(seq 1 15); do
  if openshift_namespace_uid_min "${TARGET_NS}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
patch_openshift_deployments "${TARGET_NS}"
echo "Deployed fixture in namespace ${TARGET_NS}"

if ! wait_for_rollout "${TARGET_NS}" "tls-server" "180s"; then
  echo "tls-server rollout failed — pod status:"
  oc get pods -n "${TARGET_NS}" -l app=tls-server
  oc logs -n "${TARGET_NS}" -l app=tls-server -c nginx --tail=30 2>/dev/null || true
  oc describe pod -n "${TARGET_NS}" -l app=tls-server | tail -40
  exit 1
fi
wait_for_rollout "${TARGET_NS}" "tls-client" "120s"
wait_for_log_pattern "${TARGET_NS}" "app=tls-client" "TLS/certificate|protocol mismatch|certificate|SSL|ERROR|failed|unable|refused" 60 3
wait_for_netobserv_warmup
echo "Scenario tls_issues ready (TARGET_NS=${TARGET_NS})"
