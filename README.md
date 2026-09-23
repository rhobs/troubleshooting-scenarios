# Troubleshooting Scenarios

Reproducible fault scenarios for OpenShift clusters. Each scenario deploys a specific fault (misconfiguration, resource exhaustion, network issue, etc.) on a live cluster with setup and cleanup scripts. Use them for automated evaluations, manual troubleshooting, or live demos.

## Contents

- **[evals/](evals/)**: Fault scenarios with setup/cleanup scripts and Kubernetes fixtures. Designed for automated evals of OpenShift troubleshooting tools (Lightspeed, Incident Detection, and others), but can also be run manually on any cluster.
- **[labs/](labs/)**: Multi-service scenarios with richer fault models (cascading failures, graduated alerts, red herrings). Designed for live demos and manual troubleshooting practice.

## Scenario Structure

Each scenario under `evals/scenarios/` is a self-contained directory:

```
my_scenario/
  fixtures/           Kubernetes manifests that reproduce the fault
  setup.sh            Deploys fixtures to the cluster
  cleanup.sh          Removes everything the scenario created
  evals-*.yaml        One per tool under test (e.g. OLS Agentic, OLS Classic)
```

**Scenarios are generic and not tied to OpenShift Lightspeed or any other troubleshooting tool**: they deploy real Kubernetes resources (Deployments, Services, ConfigMaps, NetworkPolicies, PrometheusRules, etc.) and create real faults on a live cluster.

To add a scenario, follow the guidelines in [CONTRIBUTING.md](CONTRIBUTING.md).

## Running Evals for OpenShift Lightspeed

Scenarios include eval definitions for OpenShift Lightspeed (OLS). The [lightspeed-evaluation](https://github.com/lightspeed-core/lightspeed-evaluation) framework orchestrates each run: deploy the fault, query OLS, score the response with a judge LLM.

### OLS Agentic

Each scenario folder contains an `evals-ols-agentic.yaml` with the eval definitions. Configure which models to test and how many repeats per scenario in `evals/system-ols-agentic.yaml`. Running `make setup-ols-agentic` automatically syncs the Agent CRs on the cluster with the agents defined in the system config. Before a real evaluation, `make eval-ols-agentic` checks that these Agent CRs are present and match the system config; if they do not, it stops and asks you to run `make setup-ols-agentic`.

```bash
make setup-ols-agentic
make eval-ols-agentic                                          # run all scenarios
make eval-ols-agentic SCENARIO=stuck_rollout                   # one scenario
make eval-ols-agentic SCENARIO=stuck_rollout,exhausted_quota   # multiple
make eval-ols-agentic TAG=alert                                # filter by tag
make eval-ols-agentic TAG=alert PREVIEW=1                      # preview matched scenarios
```

### OLS Classic

Each scenario folder that supports OLS Classic contains an `evals-ols-classic.yaml` with the eval definitions. Configure the OLS model and provider in `evals/system-ols-classic.yaml`.

```bash
make setup-ols-classic
make eval-ols-classic                                          # run all scenarios
make eval-ols-classic SCENARIO=crashlooping_pod_alert          # one scenario
```

Run `make help` for all targets and options.

### Standalone scenario setup and cleanup

To deploy one or more faults for a manual troubleshooting session or demo,
without running an evaluation:

```bash
make setup-scenario SCENARIO=stuck_rollout
make setup-scenario SCENARIO=stuck_rollout,exhausted_quota
make setup-scenario TAG=alert
make setup-scenario TAG=core PREVIEW=1       # list matches without changing the cluster
make cleanup-scenario SCENARIO=stuck_rollout,exhausted_quota
make cleanup-scenario TAG=alert PREVIEW=1
```

The `TAG` and `SCENARIO` filters use the same matching rules as the evaluation
targets. Setup leaves the selected faults running. Cleanup runs each selected
scenario's `cleanup.sh`, then the group's `cleanup.sh` once when present.
Both commands require at least one filter. They validate all scenario names and
the final match before changing the cluster.

### Requirements

- OpenShift cluster accessible via `oc login` (5.x for OLS Agentic, 4.x+ for OLS Classic)
- `OPENAI_API_KEY` exported (judge LLM)
- Python 3.13+

### Results and reports

Eval runs produce logs and reports under `evals/results/` (gitignored). Reports worth keeping can be promoted to `evals/reports/` (tracked in git).
