#!/usr/bin/env bash
set -euo pipefail

OLS_NS="${OLS_NS:-openshift-lightspeed}"
REQUIRE_OLS=0
if [ "${1:-}" = "--require-ols" ]; then
  REQUIRE_OLS=1
fi

echo "==> Preflight checks..."

# 1. oc available
if ! command -v oc >/dev/null 2>&1; then
  printf '\033[0;31mFAIL:\033[0m oc command not found\n'
  exit 1
fi
printf '\033[0;32m  OK:\033[0m oc available\n'

# 2. Logged in
if ! oc whoami >/dev/null 2>&1; then
  printf '\033[0;31mFAIL:\033[0m not logged in (oc whoami failed)\n'
  exit 1
fi
user="$(oc whoami)"
printf '\033[0;32m  OK:\033[0m logged in as %s\n' "$user"

# 3. OLS operator installed
if ! oc api-resources --api-group=ols.openshift.io 2>/dev/null | grep -q olsconfigs; then
  if [ "$REQUIRE_OLS" -eq 1 ]; then
    printf '\033[0;31mFAIL:\033[0m OLSConfig CRD not found — OLS operator not installed on this cluster (run make setup-ols-classic)\n'
    exit 1
  fi
  printf '\033[0;33mWARN:\033[0m OLSConfig CRD not found — OLS operator not installed (run make setup-ols-classic, or the suite make setup)\n'
else
  printf '\033[0;32m  OK:\033[0m OLS operator CRD found\n'

  # 4. OLS deployment available
  if oc get deployment lightspeed-app-server -n "$OLS_NS" -o name >/dev/null 2>&1; then
    avail="$(oc get deployment lightspeed-app-server -n "$OLS_NS" \
      -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || true)"
    if [ "$avail" = "True" ]; then
      printf '\033[0;32m  OK:\033[0m lightspeed-app-server is Available\n'
    else
      if [ "$REQUIRE_OLS" -eq 1 ]; then
        printf '\033[0;31mFAIL:\033[0m lightspeed-app-server exists but is not Available\n'
        exit 1
      fi
      printf '\033[0;33mWARN:\033[0m lightspeed-app-server exists but is not Available\n'
    fi
  else
    if [ "$REQUIRE_OLS" -eq 1 ]; then
      printf '\033[0;31mFAIL:\033[0m lightspeed-app-server deployment not found in %s (run make setup-ols-classic)\n' "$OLS_NS"
      exit 1
    fi
    printf '\033[0;33mWARN:\033[0m lightspeed-app-server deployment not found in %s\n' "$OLS_NS"
  fi
fi

echo "==> Preflight complete."
