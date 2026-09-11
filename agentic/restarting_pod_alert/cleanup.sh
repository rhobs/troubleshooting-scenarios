#!/usr/bin/env bash
set -euo pipefail

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$SCENARIO_DIR/../../scripts" && pwd)"
NS="data-processing"
DELETE_TIMEOUT="${DELETE_TIMEOUT:-180}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-60}"

"$SCRIPTS_DIR/check-prerequisites.sh"

if ! [[ "$DELETE_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || ! [[ "$REQUEST_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: DELETE_TIMEOUT and REQUEST_TIMEOUT must be positive integer seconds" >&2
  exit 1
fi

umask 077
TMP_DIR="$(mktemp -d)"
GET_ERROR="$TMP_DIR/get.err"
cleanup_runtime() {
  rm -rf "$TMP_DIR"
}
trap cleanup_runtime EXIT

CURRENT_CONTEXT="$(timeout --foreground "$REQUEST_TIMEOUT" oc config current-context)"
echo "Current OpenShift context: $CURRENT_CONTEXT"

if timeout --foreground "$REQUEST_TIMEOUT" oc get namespace "$NS" >/dev/null 2>"$GET_ERROR"; then
  namespace_present=true
else
  namespace_present=false
  if ! grep -qiE 'notfound|not found' "$GET_ERROR"; then
    echo "ERROR: could not determine whether namespace/$NS exists" >&2
    cat "$GET_ERROR" >&2
    exit 1
  fi
fi

if [ "$namespace_present" != true ]; then
  echo "Cleanup complete: namespace/$NS was already absent"
  exit 0
fi

echo "Deleting the dedicated namespace/$NS and all scenario resources..."
timeout --foreground "$((DELETE_TIMEOUT + 5))" \
  oc delete namespace "$NS" --ignore-not-found --wait=true --timeout="${DELETE_TIMEOUT}s"

for _ in $(seq 1 90); do
  if timeout --foreground "$REQUEST_TIMEOUT" oc get namespace "$NS" >/dev/null 2>"$GET_ERROR"; then
    sleep 2
    continue
  fi
  if grep -qiE 'notfound|not found' "$GET_ERROR"; then
    echo "Cleanup complete: namespace/$NS removed"
    exit 0
  fi
  echo "ERROR: could not verify deletion of namespace/$NS" >&2
  cat "$GET_ERROR" >&2
  exit 1
done

echo "ERROR: namespace/$NS is still present after the cleanup timeout" >&2
exit 1
