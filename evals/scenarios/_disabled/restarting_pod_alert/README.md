# Restarting pod alert

This scenario is disabled because setup is too slow for normal testing.
See the [disabled scenarios README](../README.md) for the reason and measured
setup time.

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
- Cluster nodes supporting at least one of the published Linux architectures
  (`amd64` or `arm64`).
- A fresh `data-processing` namespace; setup refuses to reuse an existing namespace. Cleanup deletes it only when its UID matches the local ownership record from setup.

Setup enables User Workload Monitoring through `scripts/enable-uwm.sh`, then relies on OpenShift reconciliation and the bounded alert waiter for the monitoring components to become usable. It builds and pushes both releases as `amd64`/`arm64` multi-architecture images and deploys them by digest. The registry port-forward is loopback-bound on Linux; on macOS it is exposed on the host so Podman's VM can reach it through `host.containers.internal`. A private temporary authentication file is used, and the forwarded registry address is never used by cluster pods.

Do not invoke setup merely to check paths: it builds images and changes the cluster. Confirm the current OpenShift context before cleanup.

## Lifecycle

To re-enable this scenario, move it back to `evals/scenarios/restarting_pod_alert`,
update the shared script paths in `setup.sh` and `cleanup.sh`, and restore its
entries in the root Makefile and active scenario table. From the repository
root, the analysis-only entrypoints will then be:

```bash
make eval-ols-agentic SCENARIO=restarting_pod_alert SETUP_MODE=run
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

Setup saves the namespace UID as soon as creation succeeds, so cleanup can
remove a partial setup too. Each evaluation run uses its own record directory.
Standalone setup and cleanup use `evals/results/.scenario-state/`. Keep these
records until cleanup is done. If an evaluation cannot finish cleanup, it prints
the record directory; retry with `SCENARIO_STATE_DIR=<directory> bash cleanup.sh`.
Cleanup skips namespaces with no matching record, including existing namespaces
and namespaces that were deleted and recreated by someone else.

The read-only `verify_fixture.py` helper is local qualification tooling. It only reads OpenShift state and logs; it is not copied into the image and is not an AgenticRun stage.

The healthy check takes a final sample after its 30-second observation window.
Its `oc` commands use the overall verification timeout, so the end of that
window does not cut short a command or an observation.

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
| Repeated setup/cleanup runs | Partial | On 2026-10-04, setup failed before the timeout fix and passed after it. Both attempts were cleaned up. More runs are needed to measure timing variability. |
| Equivalent-load healthy qualification | Not run | Healthy release remains stable for several measured affected-release failure intervals with bounded cache and no restarts. |
| Evaluator evidence access | Not run | Actual Agentic and Classic tools can read current status, previous logs, and rollout history with their assigned permissions. |
| Alert identity qualification | Not run | Firing alert labels correspond to a current affected pod/container, not merely the alert name. |
| Rubric calibration | Not run | Incomplete, incorrect, strong, and equivalent correct answers are assessed consistently. |
| Multi-model benchmark | Not run | Fresh runs distinguish reasoning outcomes from inaccessible evidence or inconsistent fixture state. |

Setup-only check on 2026-10-04 (`amd64` cluster):

- The original healthy check failed at the observation deadline while both
  pods were running with no restarts. Their cache held 2,000 entries.
- After the fix, `make setup-scenario SCENARIO=restarting_pod_alert` passed
  in 534 seconds. It checked healthy processing for at least 30 seconds,
  verified the affected release's OOM/restart evidence, and found the critical
  `DataProcessingPodRestarting` alert firing.
- Both affected pods had three `OOMKilled` restarts. Previous-container
  progress samples showed cache entries rising from 2,100 to 46,100 and
  RSS rising from about 29 MB to 269 MB while reconciliation continued.
- The healthy check also printed its RSS growth warning. This short check
  does not complete the longer healthy qualification listed above.
- No evaluations were run.

The image digests used in this check were:

| Release | Image digest |
|---|---|
| 1.0.1 | `sha256:0f0f7eb2e69797231e27ed6b3a1304a51773146d35f98be0ed3c4fe8376baef4` |
| 1.0.2 | `sha256:0922f504a70c2a4a51066552269127b3c71555b55bee0740836ad6b80274df5c` |

When qualification is performed, separate fixture failures from agent reasoning failures. Record actual build/push, baseline, rollout, first-OOM, restart, alert, and cleanup timings. Do not rewrite user-owned historical result files or claim a gate passed without supporting observations.

## Outstanding risks

- Multi-architecture Podman builds depend on base-image availability for `linux/amd64`
  and `linux/arm64`, as well as registry port-forwarding and image propagation.
- Internal registry port-forwarding, authentication, and image propagation can fail independently of the application.
- The processing rate and 256Mi limit require live calibration to keep OOM termination reliable without making the fault manifest-obvious.
- Prometheus availability, metric propagation, or evaluator RBAC can prevent alert/evidence qualification.
- Namespace cleanup is destructive for the dedicated namespace and must only be run in the intended cluster context.

The initial 8/10 assessment is a design hypothesis. The setup check above does
not complete the remaining reliability, reference stability, evidence access,
rubric, or model qualification.
