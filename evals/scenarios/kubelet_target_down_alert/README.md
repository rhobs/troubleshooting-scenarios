# Kubelet TargetDown Alert Scenario

## Overview

**OpenShift Version Requirement: 4.x only**

This scenario stresses a kubelet by creating rapid pod churn combined with sustained disk I/O operations, causing the kubelet to become unresponsive and trigger the TargetDown alert.

**Important:** This scenario works reliably on OpenShift 4.22 but does NOT trigger kubelet TargetDown on OpenShift 5.0+. OCP 5.0 includes kubelet resilience improvements that keep the kubelet endpoint responsive even under the stress conditions created by this scenario. While the scenario can stress OCP 5.0 nodes (triggering KubeletPlegDurationHigh and NodeSystemSaturation alerts), it does not achieve the primary goal of making the kubelet unreachable to Prometheus.

## Fault Mechanism

1. **Pod Accumulation**: Deployment with 28800-second (8-hour) terminationGracePeriodSeconds
2. **Disk I/O Storm**: Pods continuously write/delete 8Mi across 3 emptyDir volumes with 1-second sleep between cycles
3. **Rapid Churn**: Repeatedly scale to 75 replicas, then delete all pods
4. **Result**: Terminating pods accumulate (8hr grace period) while creating sustained disk I/O load, overwhelming the kubelet

## Expected Behavior (OCP 4.22)

- TargetDown alert fires after 5-10 iterations
- Kubelet becomes unreachable (health: down)
- Prometheus target scrape fails with timeout
- Setup script completes with SUCCESS message

## Running the Scenario

### Prerequisites
- **OpenShift 4.x cluster** (tested on 4.22; does NOT work on 5.0+)
- User-workload monitoring enabled
- Sufficient worker node capacity (scenario targets smallest worker)
- `oc` CLI access with cluster-admin permissions

### Setup
```bash
cd evals/scenarios/kubelet_target_down_alert
./setup.sh
```

Setup will:
1. Select worker node with smallest allocatable capacity
2. Create `batch-processor` namespace
3. Deploy `report-generator` with 0 replicas
4. Pin deployment to selected node via nodeSelector
5. Iteratively scale/delete pods until TargetDown fires (or timeout)

**Timeout:** Default 1200s (20 minutes), override with `STRESS_TIMEOUT=<seconds>`

### Cleanup
```bash
./cleanup.sh
```

Force-deletes all pods (ignoring grace period) and removes namespace.

## Files

- `setup.sh` - Deploys fault and waits for TargetDown alert
- `cleanup.sh` - Removes all resources
- `fixtures/deployment.yaml` - Deployment with disk I/O workload and 8hr grace period
- `fixtures/namespace.yaml` - batch-processor namespace definition
- `scripts/find-smallest-node.sh` - Selects target worker node
- `evals-ols-agentic.yaml` - OLS Agentic eval definition
- `evals-ols-classic.yaml` - OLS Classic eval definition

## Alerts

**Primary Alert:**
- `TargetDown` (warning) - Kubelet endpoint unreachable
  - Fires after 5-10 iterations on OCP 4.22
  - Prometheus target scrape to kubelet fails with timeout

## Troubleshooting

### Pods not starting
Check node capacity: `oc describe node <target-node> | grep -A 10 Allocatable`

### Setup times out
Increase timeout: `STRESS_TIMEOUT=1800 ./setup.sh`

### Cleanup stuck
Force namespace deletion: `oc patch namespace batch-processor -p '{"metadata":{"finalizers":[]}}'`

### Wrong OpenShift version
This scenario requires OpenShift 4.x. On OCP 5.0+, the kubelet remains responsive despite the stress conditions, so TargetDown does not fire.
