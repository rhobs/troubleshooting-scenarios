#!/usr/bin/env bash
set -euo pipefail

"$(cd "$(dirname "$0")/../../scripts" && pwd)/check-prerequisites.sh"

oc delete namespace ingress-layer --ignore-not-found --wait=false
