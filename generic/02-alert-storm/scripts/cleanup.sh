#!/bin/bash
set -e

echo "Scenario 02 — Alert Storm"
echo ""
echo "=== Deleting namespace ==="
oc delete namespace payments --ignore-not-found --wait

echo ""
echo "Done. All resources removed."
