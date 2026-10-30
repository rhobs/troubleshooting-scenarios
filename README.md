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
- `EVAL_OPENAI_API_KEY` when selected agents or judges use OpenAI.
- `EVAL_VERTEX_CREDENTIALS` and `EVAL_VERTEX_PROJECT_ID` when selected agents
  or judges use Google or Anthropic. The credentials value is a service account
  JSON path.

| OLS mode | Required OpenShift version |
|----------|----------------------------|
| Classic | 4.22 or newer |
| Agentic | 5.0 or newer |

```bash
export EVAL_OPENAI_API_KEY="<openai-api-key>"
# Set these when selected agents or judges use Google or Anthropic:
export EVAL_VERTEX_CREDENTIALS="/path/to/service-account.json"
export EVAL_VERTEX_PROJECT_ID="<gcp-project-id>"
```

The setup targets create the local `venv/` and install the evaluation framework.

### OLS Agentic

Each scenario folder that supports OLS Agentic contains an
`evals-ols-agentic.yaml` with the eval definitions. Configure which models to
test and how many repeats to run per scenario in
[`evals/system-ols-agentic.yaml`](evals/system-ols-agentic.yaml).
`make setup-ols-agentic` installs OLS through the same `stable` Subscription
from `redhat-operators` as Classic setup. Agentic needs OpenShift 5.0 or newer;
the catalog install also needs OLS 2.0 or newer with Agentic support.

After installation, setup keeps an existing `OLSConfig/cluster`, including
Classic providers, default model, and other settings. If the config is absent,
it creates one with an empty Classic provider list and
`agenticOLS.sandboxMode: bare-pod`. It waits for the Agentic operator and
sandbox configuration. It then reads the config selected by
`SYSTEM_CONFIG_AGENTIC`, creates credentials and providers for active agents
and selected judges, and syncs the Agent CRs. OpenAI needs
`EVAL_OPENAI_API_KEY`; Google and Anthropic need `EVAL_VERTEX_CREDENTIALS` and
`EVAL_VERTEX_PROJECT_ID`. Setup checks credentials before changing resources.
The Vertex providers use region `global`.

`SKIP_OLS_INSTALL=1` skips Namespace, OperatorGroup, and Subscription
creation. It supports both an existing full OLS installation and the standalone
Agentic quickstart in `openshift-lightspeed`. With the quickstart, setup reuses
the existing operator and sandbox configuration without creating or changing
`OLSConfig`. No migration to OLM is needed. To use images built from `main`,
install with the [Agentic quickstart](https://github.com/openshift/lightspeed-agentic-operator/tree/main/hack/quickstart),
then run `make setup-ols-agentic SKIP_OLS_INSTALL=1`.

Before a real evaluation, `make eval-ols-agentic` checks that these Agent CRs
are present and match the system config. If they do not, it stops and asks you to run
`make setup-ols-agentic` again.

```bash
make setup-ols-agentic
make setup-ols-agentic SKIP_OLS_INSTALL=1 # use OLS or the Agentic quickstart
make setup-ols-agentic SYSTEM_CONFIG_AGENTIC=evals/custom-system.yaml # custom config
make eval-ols-agentic TAG=investigation                       # run investigation cases
make eval-ols-agentic SCENARIO=stuck_rollout                  # one scenario
make eval-ols-agentic SCENARIO=stuck_rollout,exhausted_quota  # multiple
make eval-ols-agentic TAG=alert                               # filter by tag
make eval-ols-agentic TAG=alert PREVIEW=1                     # preview matched scenarios
make eval-ols-agentic TAG=investigation PREVIEW=1                  # preview investigation cases
make eval-ols-agentic TAG=remediation                          # run cases that apply fixes
```

When any selected scenario has the `remediation` tag, `SETUP_MODE=auto` (the
default) uses `run` to reset resources before each agent and repeat. Otherwise,
it uses `scenario`. You can set the mode explicitly to override this choice.

### OLS Classic

Classic needs OpenShift 4.22 or newer. OpenShift 5 is not required.

Each scenario folder that supports OLS Classic contains an
`evals-ols-classic.yaml` with the eval definitions. Choose the agents to run
in the `agents.default.agent` list in
[`evals/system-ols-classic.yaml`](evals/system-ols-classic.yaml).
Setup registers the active agents and judge models in OLS, using each entry's
`provider` and `model`. The first active agent sets the default provider and
model. OpenAI, Google, or Anthropic can be first. Remove Google and Anthropic
entries for an OpenAI-only run.

When `OLSConfig/cluster` exists, Classic setup patches only its providers and
default provider and model. It keeps Agentic settings and other shared options.
Classic setup does not change Agentic `Agent`, `LLMProvider`, or credential
Secrets. Agentic setup keeps the existing Classic configuration. You can run
the two setup targets in either order.

```bash
make setup-ols-classic
make setup-ols-classic SKIP_OLS_INSTALL=1 # use an existing operator
make eval-ols-classic TAG=investigation                       # run investigation cases
make eval-ols-classic SCENARIO=crashlooping_pod_alert         # one scenario
make eval-ols-classic TAG=alert                               # filter by tag
make eval-ols-classic TAG=alert PREVIEW=1                     # preview matched scenarios
make eval-ols-classic TAG=difficulty_medium PREVIEW=1         # preview medium cases
```

`SKIP_OLS_INSTALL=1` skips operator installation, including Namespace,
OperatorGroup, and Subscription creation. The operator and the
`openshift-lightspeed` namespace must already exist. Setup still creates
credential Secrets, creates or updates `OLSConfig`, and waits for the
app-server to be ready. Without this flag, setup skips installation only when the existing
app-server rollout is complete.

`make cleanup-ols-agentic` and `make cleanup-ols-classic` run the same uninstall.
Both remove the local `venv/`, `OLSConfig/cluster`, the OLM Subscription and CSV,
the OperatorGroup, and the entire `openshift-lightspeed` namespace. This removes
the deployments and namespaced resources for both Classic and Agentic,
including a quickstart installation. `SKIP_OLS_INSTALL=1` does not skip cleanup.
The uninstall keeps CRDs and does not remove cluster-scoped resources created
by quickstart, such as its ClusterRoles and ClusterRoleBindings.

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
Agentic evaluations also save sandbox pod logs to
`evals/results/<session>/logs/AGENTICRUN-PHASE.log`, with watcher diagnostics in
`evals/results/<session>/capture-logs.log`. Capture starts automatically before
the first scenario and stops when the session ends. Existing result files are
kept. See [sandbox logs](evals/README.md#sandbox-logs) for details and manual use.

Classic evaluations download app-server logs at evaluation and setup/cleanup
checkpoints. Files use `logs/<scenario>/<agent>-run_N.log`; calls with several
agents or repeats share a log window. See [Classic app-server logs](evals/README.md#classic-app-server-logs)
for naming, restart handling, and capture limits.

Copy reports worth keeping to `evals/reports/` to track them in Git.
See [report generation](evals/README.md#reports) for commands and scoring rules.
