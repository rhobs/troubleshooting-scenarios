#!/bin/bash
set -e

echo "=== Removing payments-np-policy NetworkPolicy ==="
oc -n payments delete networkpolicy payments-np-policy

echo ""
echo "Done. Egress traffic from payments-api is restored."
