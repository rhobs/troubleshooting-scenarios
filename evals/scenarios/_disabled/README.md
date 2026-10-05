# Disabled scenarios

Scenarios parked here are excluded from evaluation runs. Reasons include:

- The fault setup is unrealistic: an LLM can infer the damage is caused by a
  synthetic demo application rather than a genuine production issue.
- The scenario does not apply given current technical limitations of
  Lightspeed Agentic.
- The scenario tests a capability (e.g. hygiene review, pre-flight analysis)
  that is not specific to troubleshooting.
- The setup takes too long for normal testing.

These scenarios are candidates for revision and re-enablement in the future.


## Scenarios

| Scenario | Reason |
|----------|--------|
| `missing_alerts` | The agent lacks RBAC permissions to read PrometheusRule resources, so it cannot inspect the existing rules and proposes generic alert categories instead of concrete expressions (0/4 correctness). |
| `silent_alerts` | The agent lacks RBAC permissions to read PrometheusRule resources, so it cannot see the misspelled metric names and speculates about unrelated causes (0/4 correctness). |
| `noncompliant_workloads` | Tests workload hygiene review (probes, limits, pinned tags), not troubleshooting. Not specific to the troubleshooting evaluation. |
| [`restarting_pod_alert`](restarting_pod_alert/README.md) | The scenario works, but setup took 534 seconds (about nine minutes) in the successful check on 2026-10-04. It builds and pushes two multi-architecture images, checks healthy processing, then waits for three OOM restarts and a firing alert. This is too slow for normal testing. Re-enable it when setup is faster or use it in a separate slow test suite. |
| `unsafe_rollout` | Tests pre-flight manifest review (dropped probes, unpinned image, removed securityContext), not troubleshooting. Not specific to the troubleshooting evaluation. |
