#!/usr/bin/env bash
set -euo pipefail

# Find the worker node with the smallest allocatable capacity.
# Used by kubelet_target_down scenario to select a node to stress test.
# Prefers pure worker nodes; falls back to dual-role nodes in compact clusters.
# Output: Node name to stdout
# Exit: 0 on success, 1 if no worker nodes found

# Get all worker nodes with their allocatable resources and roles
WORKERS=$(oc get nodes -l node-role.kubernetes.io/worker \
  -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.allocatable.cpu}{" "}{.status.allocatable.memory}{" "}{.metadata.labels.node-role\.kubernetes\.io/control-plane}{"\n"}{end}')

if [ -z "$WORKERS" ]; then
  echo "ERROR: No worker nodes found" >&2
  exit 1
fi

# Separate pure worker nodes from dual-role (worker+control-plane) nodes
PURE_WORKERS=""
DUAL_ROLE_WORKERS=""
while IFS= read -r line; do
  if [[ "$line" =~ ^([^\ ]+)\ ([^\ ]+)\ ([^\ ]+)\ *$ ]]; then
    # No control-plane label (pure worker)
    PURE_WORKERS="${PURE_WORKERS}${line}\n"
  elif [[ "$line" =~ ^([^\ ]+)\ ([^\ ]+)\ ([^\ ]+)\ .+$ ]]; then
    # Has control-plane label (dual-role)
    DUAL_ROLE_WORKERS="${DUAL_ROLE_WORKERS}${line}\n"
  fi
done <<< "$WORKERS"

# Prefer pure workers; fall back to dual-role if none exist
if [ -n "$PURE_WORKERS" ]; then
  SELECTED_WORKERS="$PURE_WORKERS"
elif [ -n "$DUAL_ROLE_WORKERS" ]; then
  echo "WARNING: No pure worker nodes found. Using dual-role node (worker+control-plane) in compact cluster." >&2
  echo "WARNING: This will stress control-plane components." >&2
  SELECTED_WORKERS="$DUAL_ROLE_WORKERS"
else
  echo "ERROR: No usable worker nodes found" >&2
  exit 1
fi

# Process with awk to calculate scores and find minimum
# shellcheck disable=SC2028
echo -e "$SELECTED_WORKERS" | awk '
function cpu_to_millis(cpu) {
  # Handle formats like "4", "4000m", etc.
  if (cpu ~ /m$/) {
    sub(/m$/, "", cpu)
    return cpu + 0
  }
  return cpu * 1000
}

function mem_to_ki(mem) {
  # Handle Ki, Mi, Gi suffixes
  if (mem ~ /Ki$/) {
    sub(/Ki$/, "", mem)
    return mem + 0
  } else if (mem ~ /Mi$/) {
    sub(/Mi$/, "", mem)
    return mem * 1024
  } else if (mem ~ /Gi$/) {
    sub(/Gi$/, "", mem)
    return mem * 1024 * 1024
  }
  return mem + 0
}

{
  if (NF < 3 || $1 == "") next  # Skip empty lines
  node = $1
  cpu_millis = cpu_to_millis($2)
  mem_ki = mem_to_ki($3)

  # Score: normalize memory to similar scale as CPU
  # CPU in millicores, memory converted to rough equivalent
  score = cpu_millis + (mem_ki / 1024)

  if (NR == 1 || score < min_score) {
    min_score = score
    min_node = node
  } else if (score == min_score && node < min_node) {
    # Tie-breaker: alphabetical
    min_node = node
  }
}

END {
  if (min_node != "") {
    print min_node
  } else {
    print "ERROR: Could not determine smallest node" > "/dev/stderr"
    exit 1
  }
}
'
