#!/usr/bin/env bash
set -euo pipefail

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$SCENARIO_DIR/../../../../scripts" && pwd)"
# shellcheck source=scripts/scenario-namespace.sh
source "$SCRIPTS_DIR/scenario-namespace.sh"
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
trap 'rm -rf "$TMP_DIR"' EXIT

CURRENT_CONTEXT="$(timeout --foreground "$REQUEST_TIMEOUT" oc config current-context)"
echo "Current OpenShift context: $CURRENT_CONTEXT"

if scenario_namespace_owned "$NS" timeout --foreground "$REQUEST_TIMEOUT" oc; then
  :
else
  status=$?
  if [ "$status" -eq 1 ]; then exit 0; fi
  exit "$status"
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
    rm -f "$SCENARIO_STATE_DIR/$NS.uid"
    echo "Cleanup complete: namespace/$NS removed"
    exit 0
  fi
  echo "ERROR: could not verify deletion of namespace/$NS" >&2
  cat "$GET_ERROR" >&2
  exit 1
done

echo "ERROR: namespace/$NS is still present after the cleanup timeout" >&2
exit 1
