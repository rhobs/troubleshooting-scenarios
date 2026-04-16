#!/bin/bash
set -e

echo "=== Deleting namespaces ==="
oc delete namespace shared-services payments --ignore-not-found --wait

echo ""
echo "Done. All resources removed."
