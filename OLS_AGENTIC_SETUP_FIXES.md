# OLS Agentic Setup - Manual Configuration Required

This document covers the manual configuration steps required after running `make setup-ols-agentic` on OpenShift 4.22+.

## Context

The OLS operator (lightspeed-operator v2.0.1) and Agentic operator are installed, but three critical configurations are missing and must be created manually:

1. **Agentic Configuration ConfigMap** - Sandbox pod spec
2. **Approval Policy** - Auto-approval for evaluations
3. **RBAC** - ServiceAccounts for agents and sandboxes

## Symptoms

- `make setup-ols-agentic` times out waiting for `lightspeed-agentic-configuration` ConfigMap
- AgenticRuns fail with "operator configuration not yet available"
- AgenticRuns get stuck in "pending approval"
- AgenticRuns fail with RBAC errors about missing ServiceAccounts

## Fix 1: Create Agentic Configuration ConfigMap

The operator expects this ConfigMap but doesn't create it automatically.

```bash
cat <<'EOF' | oc apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: lightspeed-agentic-configuration
  namespace: openshift-lightspeed
data:
  sandbox-pod-spec: |
    {
      "serviceAccountName": "lightspeed-agentic-sandbox",
      "containers": [{
        "name": "sandbox",
        "image": "registry.redhat.io/openshift-lightspeed/lightspeed-agentic-sandbox-rhel9@sha256:1ae2197fcde6357fc1b49b0799e9107196ca32cfa727c1cadd3dc9815bb1c9c5",
        "resources": {
          "requests": {
            "memory": "512Mi",
            "cpu": "200m"
          },
          "limits": {
            "memory": "2Gi",
            "cpu": "2000m"
          }
        }
      }]
    }
EOF
```

**Verify:**
```bash
oc get configmap -n openshift-lightspeed lightspeed-agentic-configuration
```

## Fix 2: Create Approval Policy for Auto-Approval

Without this, all AgenticRuns wait indefinitely for manual approval.

**⚠️ WARNING - Shared Cluster Impact:**  
The ApprovalPolicy resource named `cluster` is a singleton that affects **all AgenticRuns cluster-wide**. On a shared cluster, this configuration will auto-approve Analysis, Execution, Verification, and Escalation phases for every AgenticRun from any namespace, not just evaluation runs.

**Recommendation:** Only apply this on isolated evaluation clusters. On shared clusters, either:
1. Use manual approval (don't create this resource)
2. Back up any existing policy first: `oc get approvalpolicy cluster -o yaml > policy-backup.yaml`
3. Restore after evaluations: `oc apply -f policy-backup.yaml`

```bash
cat <<'EOF' | oc apply -f -
apiVersion: agentic.openshift.io/v1alpha1
kind: ApprovalPolicy
metadata:
  name: cluster
spec:
  stages:
    - name: Analysis
      approval: Automatic
    - name: Execution
      approval: Automatic
    - name: Verification
      approval: Automatic
    - name: Escalation
      approval: Automatic
  maxConcurrentRuns: 10
EOF
```

**Note:** The name **must** be `cluster` (singleton resource).

**Verify:**
```bash
oc get approvalpolicy cluster -o yaml
```

## Fix 3: Create RBAC for Agent and Sandbox

AgenticRuns need ServiceAccounts with cluster-reader access.

```bash
cat <<'EOF' | oc apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: lightspeed-agent
  namespace: openshift-lightspeed
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: lightspeed-agent-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-reader
subjects:
- kind: ServiceAccount
  name: lightspeed-agent
  namespace: openshift-lightspeed
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: lightspeed-agentic-sandbox
  namespace: openshift-lightspeed
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: lightspeed-agentic-sandbox-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-reader
subjects:
- kind: ServiceAccount
  name: lightspeed-agentic-sandbox
  namespace: openshift-lightspeed
EOF
```

**Verify:**
```bash
oc get sa -n openshift-lightspeed | grep -E "(lightspeed-agent|lightspeed-agentic-sandbox)"
oc get clusterrolebinding | grep lightspeed-a
```

## Testing the Configuration

**First, check which agents are configured:**
```bash
oc get agent -n openshift-lightspeed -o jsonpath='{.items[*].metadata.name}'
```

Create a test AgenticRun using any configured agent name:

```bash
# Replace <AGENT_NAME> with an agent from the list above
cat <<'EOF' | oc apply -f -
apiVersion: agentic.openshift.io/v1alpha1
kind: AgenticRun
metadata:
  name: test-config
  namespace: openshift-lightspeed
spec:
  analysis:
    agent: <AGENT_NAME>  # e.g., openai-gpt-6-luna, google-gemini-3-8-flash
  request: "Test: List all namespaces in the cluster."
EOF
```

**Monitor progress:**
```bash
# Watch status
oc get agenticrun test-config -n openshift-lightspeed -w

# Check completion
oc get agenticrun test-config -n openshift-lightspeed -o jsonpath='{.status.conditions[?(@.type=="Analyzed")].reason}'
```

**Expected result:** Status should progress through:
1. Pending → Running (sandbox pod created)
2. Analyzed: Succeeded or NoActionRequired
3. Terminal time set

**Clean up test:**
```bash
oc delete agenticrun test-config -n openshift-lightspeed
```

## Why These Are Missing

These resources should be created automatically by the OLS/Agentic operators based on:
- `OLSConfig/cluster` with `spec.agenticOLS.sandboxMode: bare-pod`
- `AgenticOLSConfig/cluster` (cluster-scoped)

However, in OpenShift 4.22 with lightspeed-operator v2.0.1, the reconciliation logic doesn't create these resources. This may be:
- A known limitation in v2.0.x
- Fixed in a later operator version
- Related to the timing of when AgenticOLSConfig was created vs operator startup

## Root Cause Investigation

The agentic operator logs showed:
```
INFO setup Sandbox CRDs not found, defaulting to bare-pod mode
```

The operator started before `AgenticOLSConfig/cluster` existed and never re-reconciled after it was created. Restarting the operator didn't help because the reconciliation controller for `AgenticOLSConfig` doesn't implement ConfigMap creation logic in this version.

## Automation Script

To automate these fixes after `make setup-ols-agentic`:

```bash
#!/usr/bin/env bash
# scripts/fix-agentic-config.sh
set -euo pipefail

NAMESPACE="openshift-lightspeed"

echo "==> Creating lightspeed-agentic-configuration ConfigMap..."
cat <<'EOF' | oc apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: lightspeed-agentic-configuration
  namespace: openshift-lightspeed
data:
  sandbox-pod-spec: |
    {
      "serviceAccountName": "lightspeed-agentic-sandbox",
      "containers": [{
        "name": "sandbox",
        "image": "registry.redhat.io/openshift-lightspeed/lightspeed-agentic-sandbox-rhel9@sha256:1ae2197fcde6357fc1b49b0799e9107196ca32cfa727c1cadd3dc9815bb1c9c5",
        "resources": {
          "requests": {"memory": "256Mi", "cpu": "100m"},
          "limits": {"memory": "512Mi", "cpu": "500m"}
        }
      }]
    }
EOF

echo "==> Creating ApprovalPolicy for auto-approval..."
cat <<'EOF' | oc apply -f -
apiVersion: agentic.openshift.io/v1alpha1
kind: ApprovalPolicy
metadata:
  name: cluster
spec:
  stages:
    - name: Analysis
      approval: Automatic
    - name: Execution
      approval: Automatic
    - name: Verification
      approval: Automatic
    - name: Escalation
      approval: Automatic
  maxConcurrentRuns: 10
EOF

echo "==> Creating RBAC for agents and sandboxes..."
cat <<'EOF' | oc apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: lightspeed-agent
  namespace: openshift-lightspeed
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: lightspeed-agent-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-reader
subjects:
- kind: ServiceAccount
  name: lightspeed-agent
  namespace: openshift-lightspeed
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: lightspeed-agentic-sandbox
  namespace: openshift-lightspeed
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: lightspeed-agentic-sandbox-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-reader
subjects:
- kind: ServiceAccount
  name: lightspeed-agentic-sandbox
  namespace: openshift-lightspeed
EOF

echo "==> Configuration complete!"
echo "==> Verify with: oc get configmap,approvalpolicy,sa -n $NAMESPACE"
```

**Save the script above to `scripts/fix-agentic-config.sh`, then make it executable:**
```bash
chmod +x scripts/fix-agentic-config.sh
```

## Integration into Makefile

**Note:** The ConfigMap must exist before `setup-ols-agentic.sh` waits for it, so the fix script cannot be added to the end of the Makefile target. Instead, either:

1. **Run manually after initial setup failure:**
   ```bash
   make setup-ols-agentic  # Will timeout waiting for ConfigMap
   ./scripts/fix-agentic-config.sh
   # Operator will reconcile and setup can proceed
   ```

2. **Or create a two-phase setup:**
   ```makefile
   setup-ols-agentic-prereqs:
       @bash $(SCRIPTS_DIR)/fix-agentic-config.sh

   setup-ols-agentic: setup-venv setup-ols-agentic-prereqs
       @echo "==> Using config: $(SYSTEM_CONFIG_AGENTIC)"
       @bash $(SCRIPTS_DIR)/preflight.sh
       @SYSTEM_CONFIG_AGENTIC="$(SYSTEM_CONFIG_AGENTIC)" bash $(SCRIPTS_DIR)/setup-ols-agentic.sh
       @venv/bin/python3 $(SCRIPTS_DIR)/sync-agent-crs.py "$(SYSTEM_CONFIG_AGENTIC)"
   ```

**For now, run manually:**
```bash
# First-time setup
./scripts/fix-agentic-config.sh  # Create ConfigMap, ApprovalPolicy, RBAC
make setup-ols-agentic            # Now proceeds without timeout
```
