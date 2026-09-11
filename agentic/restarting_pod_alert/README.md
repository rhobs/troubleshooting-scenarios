# Restarting pod alert

## Purpose

This scenario benchmarks analysis-only troubleshooting for a report-processing workload that restarts repeatedly during normal processing. The symptom-based name does not identify the failure mechanism: the agent must correlate pod termination state, previous-container logs, progress telemetry, and rollout history.

The scenario is **Normal difficulty** and measures a focused capability: distinguishing application-driven memory growth from a container memory limit that is merely too small. Passing this case does not demonstrate broad senior-engineer troubleshooting competence.

The scenario runs in the dedicated `data-processing` namespace and uses the `DataProcessingPodRestarting` critical alert. Both OpenShift Lightspeed Agentic and OLS Classic use the same fixture and separate analysis-only evaluation definitions. Neither evaluation asks the agent to mutate the cluster or verify a recovery.

## Architecture

The fixture builds two releases of the same report-processing worker and publishes them to the OpenShift internal registry:

- **Release 1.0.1** bounds recent report retention.
- **Release 1.0.2** processes the same useful workload but does not evict completed reports.
- Both releases use the same batch settings and resource limits.
- Setup deploys 1.0.1 first, confirms successful processing and reconciliation, then updates the same Deployment to 1.0.2.
- The affected release retains completed reports until the kernel terminates the container for exceeding its cgroup memory limit.
- The previous ReplicaSet remains available so the release transition and known-good rollback are discoverable.

The worker emits flushed JSONL events for completed reports and periodic progress. Progress includes processed records, retained cache entries, reconciliation counts, and current RSS. It does not print a final diagnosis or expose source code through a mounted resource.

## Prerequisites

- An authenticated OpenShift CLI context with permission to create and delete the dedicated `data-processing` namespace.
- Podman, Python 3, `curl`, and `timeout` on the setup machine.
- Access to the OpenShift internal image registry and permission to push to `data-processing/report-generator`.
- Permission to apply `cluster-monitoring-config` in `openshift-monitoring`; setup invokes `scripts/enable-uwm.sh` to enable User Workload Monitoring using the same lifecycle as the other alert scenarios.
- A cluster node architecture compatible with the local Podman build architecture.
- Exclusive ownership of `data-processing`; setup refuses to reuse an existing namespace and cleanup deletes the entire namespace.

Setup enables User Workload Monitoring through `scripts/enable-uwm.sh`, then relies on OpenShift reconciliation and the bounded alert waiter for the monitoring components to become usable. It uses a loopback-bound registry port-forward and a private temporary authentication file. It automatically builds and pushes both releases. Images are deployed by digest; the local forwarded registry address is never used by cluster pods.

Do not invoke setup merely to check paths: it builds images and changes the cluster. Confirm the current OpenShift context before cleanup.

## Lifecycle

From `agentic/`, the analysis-only entrypoints are:

```bash
make eval SCENARIO=restarting_pod_alert SETUP_MODE=run
make eval-ols-classic SCENARIO=restarting_pod_alert
```

The scenario lifecycle is:

1. Create the dedicated namespace.
2. Build and push releases 1.0.1 and 1.0.2.
3. Apply the restart alert and healthy Deployment.
4. Observe completed reports, cache reconciliation, and stable healthy processing.
5. Roll the Deployment to the affected digest.
6. Verify current-pod OOM termination, repeated restarts, and pre-OOM progress evidence.
7. Wait for `DataProcessingPodRestarting` at critical severity.
8. Leave the affected release running for the evaluation.
9. Delete the dedicated namespace with `cleanup.sh` after evidence collection.

The read-only `verify_fixture.py` helper is local qualification tooling. It only reads OpenShift state and logs; it is not copied into the image and is not an AgenticRun stage.

## Evaluation contract

The evaluations are analysis-only:

- Expected Agentic status is `Completed` with `Analyzed=True`.
- No execution or verification phases are included.
- No remediation evaluation is included.
- The correct recommendation is durable cache bounding/eviction or restoration of the known-good release.
- Increasing the memory limit may be an interim mitigation, but by itself only delays recurrence.

The expected answer does not require a specific release number, exact RSS value, implementation language, source expression, or source inspection. Equivalent evidence-based explanations are valid.

## Proposed-design credibility assessment

**8/10 proposed-design credibility.** This is a qualitative design assessment, not a live-validated benchmark score or measured model accuracy. Reassess it only after the evidence gates below are completed.

### Strengths

- A release omitting cache eviction is a plausible production regression rather than an artificial allocation loop.
- Useful report processing and reconciliation continue while the cache grows.
- Completed work, retained entries, RSS, previous-container logs, restart status, and rollout history provide complementary diagnostic evidence.
- Healthy and affected releases share processing logic, workload settings, and limits, supporting comparison with a known-good revision.
- The scenario name and user request describe repeated restarts rather than the root cause.
- Digest-based deployment and fresh healthy-to-affected setup improve reproducibility.
- Analysis-only scoring measures diagnosis and recommendations without claiming to measure executed remediation.

### Limitations

- The records are locally generated and the application is intentionally small; reconciliation must remain useful rather than decorative.
- Explicit cache/RSS telemetry, one workload, and a two-release history make this a focused Normal-difficulty benchmark, not a broad production-estate test.
- CPU throttling, restart backoff, log retention, architecture, and monitoring delay can affect evidence visibility between runs.
- A rubric that accepts only `OOMKilled` or a limit increase would not distinguish superficial observations from understanding the retention defect; exact wording requirements would reject equivalent correct answers unfairly.

## Qualitative answer calibration

| Answer | Assessment |
|---|---|
| “The pod was OOMKilled.” | Correct observation but incomplete diagnosis; it does not explain the memory growth. |
| “Increase its memory limit.” | Insufficient as the sole remedy; it may delay recurrence without fixing retention. |
| “Completed reports keep accumulating after processing, and cache entries and memory rise before OOM termination. Eviction is ineffective; restore the known-good release or bound retention.” | Strong evidence-based diagnosis and durable recommendation. |

Credit equivalent explanations and justified interim mitigations when accompanied by a durable remedy. Do not require a particular release number, exact telemetry value, source inspection, or wording.

## Validation status

This README records the status of the implementation and qualification gates. It must be updated with actual observations after authorized runs; no results are inferred here.

| Evidence requirement | Status | Required evidence |
|---|---|---|
| Repeated setup/cleanup runs | Not run | Run counts, failures, timing variability, image digests, architecture, and sanitized runtime samples. |
| Equivalent-load healthy qualification | Not run | Healthy release remains stable for several measured affected-release failure intervals with bounded cache and no restarts. |
| Evaluator evidence access | Not run | Actual Agentic and Classic tools can read current status, previous logs, and rollout history with their assigned permissions. |
| Alert identity qualification | Not run | Firing alert labels correspond to a current affected pod/container, not merely the alert name. |
| Rubric calibration | Not run | Incomplete, incorrect, strong, and equivalent correct answers are assessed consistently. |
| Multi-model benchmark | Not run | Fresh runs distinguish reasoning outcomes from inaccessible evidence or inconsistent fixture state. |

When qualification is performed, separate fixture failures from agent reasoning failures. Record actual build/push, baseline, rollout, first-OOM, restart, alert, and cleanup timings. Do not rewrite user-owned historical result files or claim a gate passed without supporting observations.

## Outstanding risks

- Local Podman builds depend on base-image availability and architecture compatibility.
- Internal registry port-forwarding, authentication, and image propagation can fail independently of the application.
- The processing rate and 256Mi limit require live calibration to keep OOM termination reliable without making the fault manifest-obvious.
- Prometheus availability, metric propagation, or evaluator RBAC can prevent alert/evidence qualification.
- Namespace cleanup is destructive for the dedicated namespace and must only be run in the intended cluster context.

The initial 8/10 assessment is a design hypothesis. Live reliability, reference stability, evidence access, rubric behavior, and model outcomes remain unperformed until explicitly qualified.
