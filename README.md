# Troubleshooting Scenarios

Reproducible OpenShift scenarios for AI-assisted troubleshooting. Each scenario deploys the environment and introduces a fault.

## Scenario suites

| Suite | Description |
|-------|-------------|
| [generic/](generic/) | General OpenShift fault-injection scenarios (database connection exhaustion, cascading alert storm). |
| [kiali-ossm/](kiali-ossm/) | Service-mesh troubleshooting scenarios using Kiali/OSSM MCP tools and OpenShift Lightspeed. |

### generic

| Scenario | Description |
|----------|-------------|
| [01-payments-api-failure](generic/01-payments-api-failure/) | A routine rollout deploys a buggy version of the reporting service, which leaks database connections, exhausts a shared PostgreSQL pool, and causes payment failures in a separate namespace. |
| [02-alert-storm](generic/02-alert-storm/) | A misconfigured ConfigMap causes payments-api to fail, triggering a cascade of alerts across all dependent services. |

### kiali-ossm

Evaluation scenarios that test AI-assisted diagnosis of Istio/Kiali mesh problems. See [`kiali-ossm/README.md`](kiali-ossm/README.md) for setup instructions and a full description of each scenario.

---

## Lightspeed evaluation setup

The `kiali-ossm` scenarios are evaluated using [`lightspeed-evaluation`](https://github.com/lightspeed-core/lightspeed-evaluation), a framework that sends queries to an [OpenShift Lightspeed](https://github.com/openshift/lightspeed-service) (OLS) instance and scores responses with a judge LLM.

### Requirements

- Python 3.11, 3.12, or 3.13 (`lightspeed-evaluation` does not support 3.14+)
- A running OLS instance reachable from your machine (configure `api.api_base` in `kiali-ossm/system.yaml`)
- `OPENAI_API_KEY` exported in your shell (used by the judge LLM)

### Install

From the repository root, create a virtualenv and install the evaluation framework:

```bash
make setup-ols-evaluation
```

This creates `./venv` and installs `lightspeed-evaluation` directly from the `lightspeed-core` GitHub repository. You only need to run this once (or after deleting the venv).

### Run evaluations

Change into the scenario suite directory and run the desired target:

```bash
cd kiali-ossm/
make test                          # run all MCP-enabled scenarios
make check_mesh_status-test        # run a single scenario
make test-without-mcp              # run the no-Kiali baseline
```

Results are written to `kiali-ossm/results/` as CSV and JSON files.
