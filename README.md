# Troubleshooting Scenarios

Reproducible fault scenarios for OpenShift clusters. Each scenario deploys a
specific fault (misconfiguration, resource exhaustion, network issue, etc.) on a
live cluster with setup and cleanup scripts. Use them for automated evaluations,
manual troubleshooting, or live demos.

Run `make help` for all targets and options.

## Contents

- [**evals/**](evals/): Fault scenarios with setup/cleanup scripts and Kubernetes
  fixtures. Designed for automated evals of OpenShift troubleshooting tools
  (Lightspeed, Incident Detection, and others), but can also be run manually on
  any cluster.
- [**labs/**](labs/): Multi-service scenarios with richer fault models (cascading
  failures, graduated alerts, red herrings). Designed for live demos and manual
  troubleshooting practice.

## Scenario Structure

Each scenario under `evals/scenarios/` is a self-contained directory:

```text
my_scenario/
  fixtures/          Kubernetes manifests that reproduce the fault
  setup.sh           Deploys fixtures to the cluster
  cleanup.sh         Removes everything the scenario created
  evals-*.yaml       One per tool under test (e.g. OLS Agentic, OLS Classic)
```

**Scenarios are generic and not tied to OpenShift Lightspeed or any other
troubleshooting tool**: they deploy real Kubernetes resources (Deployments,
Services, ConfigMaps, NetworkPolicies, PrometheusRules, etc.) and create real
faults on a live cluster.

To add a scenario, follow the guidelines in [CONTRIBUTING.md](CONTRIBUTING.md).

## Running Evals for OpenShift Lightspeed

Scenarios include eval definitions for OpenShift Lightspeed (OLS). The
[lightspeed-evaluation](https://github.com/lightspeed-core/lightspeed-evaluation)
framework runs each evaluation: deploy the fault, query OLS, and score the
response with a judge LLM.

### Requirements and environment variables

Run the commands below from the repository root. You need:

- An OpenShift cluster and an active `oc login` session.
- Python 3.11+ for the evaluation environment.
- `EVAL_OPENAI_API_KEY` for the judge and OpenAI models.
- `EVAL_VERTEX_CREDENTIALS` and `EVAL_VERTEX_PROJECT_ID` when active models use
  Google or Anthropic. The credentials value is a service account JSON path.

```bash
export EVAL_OPENAI_API_KEY="<openai-api-key>"
# Also set these when using Google or Anthropic:
export EVAL_VERTEX_CREDENTIALS="/path/to/service-account.json"
export EVAL_VERTEX_PROJECT_ID="<gcp-project-id>"
```

The setup targets create the local `venv/` and install the evaluation framework.

### OLS Agentic

Each scenario folder that supports OLS Agentic contains an
`evals-ols-agentic.yaml` with the eval definitions. Configure which models to
test and how many repeats to run per scenario in
[`evals/system-ols-agentic.yaml`](evals/system-ols-agentic.yaml).
The cluster needs the Lightspeed Agentic operator. Running
`make setup-ols-agentic` creates the OpenAI credentials and provider using
`EVAL_OPENAI_API_KEY`. When `EVAL_VERTEX_CREDENTIALS` and
`EVAL_VERTEX_PROJECT_ID` are set, it also creates the Google and Anthropic
Vertex providers. Both use region `global`; there is no region variable.
These are the same credential variables used by Classic setup.

It then syncs the Agent CRs on the cluster with the agents
defined in the system config; it does not install the operator. Before a real
evaluation, `make eval-ols-agentic` checks that these Agent CRs are present and
match the system config. If they do not, it stops and asks you to run
`make setup-ols-agentic` again.

```bash
make setup-ols-agentic
make eval-ols-agentic TAG=investigation                       # run investigation cases
make eval-ols-agentic SCENARIO=stuck_rollout                  # one scenario
make eval-ols-agentic SCENARIO=stuck_rollout,exhausted_quota  # multiple
make eval-ols-agentic TAG=alert                               # filter by tag
make eval-ols-agentic TAG=alert PREVIEW=1                     # preview matched scenarios
make eval-ols-agentic TAG=investigation PREVIEW=1                  # preview investigation cases
make eval-ols-agentic TAG=remediation SETUP_MODE=run           # run cases that apply fixes
```

For evaluations that change cluster resources, use `SETUP_MODE=run` to reset
resources before each agent and repeat.

### OLS Classic

Each scenario folder that supports OLS Classic contains an
`evals-ols-classic.yaml` with the eval definitions. Choose the agents to run
in the `agents.default.agent` list in
[`evals/system-ols-classic.yaml`](evals/system-ols-classic.yaml).
Setup registers the active agents and judge models in OLS, using each entry's
`provider` and `model`. The first active agent sets the default model and must
use OpenAI. Remove Google and Anthropic entries for an OpenAI-only run.

```bash
make setup-ols-classic
make eval-ols-classic TAG=investigation                       # run investigation cases
make eval-ols-classic SCENARIO=crashlooping_pod_alert         # one scenario
make eval-ols-classic TAG=alert                               # filter by tag
make eval-ols-classic TAG=alert PREVIEW=1                     # preview matched scenarios
make eval-ols-classic TAG=difficulty_medium PREVIEW=1         # preview medium cases
```

Setup uses the `openshift-lightspeed` namespace. Both evaluation targets require
`SCENARIO`, `TAG`, or both, including with `PREVIEW=1`. Without a filter, Make
stops before setup or evaluation starts.
See the [eval guide](evals/README.md#running-automated-evals) for filters,
setup modes, and failure handling.

Tags describe the workflow (`investigation` or `remediation`), difficulty, and
optional selections such as `core`, `alert`, or a scenario group. The Make
target selects Agentic or Classic; these mode names are no longer tags.
`TAG=alert` selects alert investigation cases. Use `TAG=remediation` for
cases that apply fixes. Multiple tags use OR: `TAG=core,alert` selects cases
with either tag. See the [tag guide](evals/README.md#tags) for all current tags.

## Manual setup and cleanup

Deploy faults without running an evaluation:

```bash
make setup-scenario SCENARIO=blocked_deployment PREVIEW=1
make setup-scenario SCENARIO=blocked_deployment
# Investigate the fault, then remove it:
make cleanup-scenario SCENARIO=blocked_deployment
```

Both targets require `SCENARIO`, `TAG`, or both. Use commas to select several
scenarios. Setup leaves faults running; cleanup removes scenario resources
and shared group resources where present.

## Results

Logs and generated reports are saved under `evals/results/` (ignored by Git).
Copy reports worth keeping to `evals/reports/` to track them in Git.
See [report generation](evals/README.md#reports) for commands and scoring rules.
