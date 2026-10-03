# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.
`CLAUDE.md` is a symlink to this file.

## Project Purpose

Reproducible fault scenarios for OpenShift clusters. Each scenario deploys a specific fault on a live cluster with setup and cleanup scripts. Scenarios are used for automated evaluations of OpenShift troubleshooting tools (Lightspeed, Incident Detection) and for manual troubleshooting practice.

## Repository Structure

```
evals/            Fault scenarios for automated evals
  scenarios/      Scenario definitions (fixtures, evals, setup/cleanup)
  system-*.yaml   Evaluation framework configs (models, repeats, scoring)
  reports/        Curated reports (tracked, manually promoted from results/)
  results/        Generated output (gitignored): eval logs and reports
labs/             Multi-service scenarios for demos and manual troubleshooting
scripts/          Shared shell scripts (venv, OLS, eval runners)
Makefile          Orchestrates eval runs for OLS Agentic and OLS Classic
```

### Scenario structure

Each scenario under `evals/scenarios/` is a self-contained directory:

- `setup.sh` deploys fixtures to the cluster (creates namespaces, resources, faults)
- `cleanup.sh` removes everything the scenario created
- `fixtures/` contains the Kubernetes manifests applied by `setup.sh`
- `evals-*.yaml` contains eval definitions, one per tool under test (e.g. `evals-ols-agentic.yaml`, `evals-ols-classic.yaml`)

### Adding or modifying scenarios

When adding, removing, or renaming scenarios under `evals/scenarios/`, keep `evals/scenarios/README.md` (scenario table) and the root `Makefile` (scenario variables) in sync.

After adding or modifying a scenario, run the `review-scenario` skill to check for naming leaks, revealing comments, and unrealistic fault setups.

### Root Makefile

The root Makefile has all targets. Run `make help` for the full list.

```bash
make tools              # Install local lint tools in .tools/
make lint               # Install tools if needed, then run all linters
make setup-ols-agentic  # Install venv + sync Agent CRs
make setup-ols-classic  # Install venv + OLS classic
make eval-ols-agentic TAG=investigation # Run OLS agentic investigation cases
make eval-ols-classic TAG=investigation # Run OLS classic investigation cases
make cleanup-ols-classic # Remove venv + OLS classic
```

## Architecture: labs/payments-api-failure (Database Connection Exhaustion)

Services share a PostgreSQL database with `max_connections=20`. The fault: `reporting-service` v1.0.2 accumulates database connections without closing them, exhausting the shared pool and causing payments-api to return 503s.

Two deployment modes control difficulty:

- **`make deploy-easy`**: single `payments` namespace, per-service DB users (`payments`, `reporting`), only 1 critical alert (payment error rate) and 1 warning (DB connections), no red herring.
- **`make deploy`** (hard): two namespaces (`payments`, `shared-services`), shared `dbuser` DB account, graduated alerts (warning + critical for both payment and DB), `reconciliation-service` red herring (always in CrashLoopBackOff). Accepts `SINGLE_NAMESPACE=1` to collapse into one namespace while keeping other hard-mode traits.

The deploy script always works on a temp copy of manifests, applying sed transformations per mode. Operational scripts (break, fix, cleanup, etc.) auto-detect the deployment mode by checking whether the `shared-services` namespace exists.

### Key Paths

- `labs/payments-api-failure/README.md` -- scenario overview and components
- `labs/payments-api-failure/manifests/payments/` -- Kubernetes manifests for the payments namespace
- `labs/payments-api-failure/manifests/shared-services/` -- Kubernetes manifests for the shared-services namespace
- `labs/payments-api-failure/scripts/` -- shell scripts that implement each Make target
- `labs/payments-api-failure/reporting-service/v1.0.1/` -- healthy version
- `labs/payments-api-failure/reporting-service/v1.0.2/` -- buggy version (connection leak + division by zero)

## Architecture: labs/alert-storm (Cascading Alert Storm)

Single `payments` namespace with five microservices:

- **`payments-api`**: Central service that processes payments. Loads config from a mounted ConfigMap.
- **`checkout-service`**, **`order-processor`**, **`refund-service`**, **`notification-service`**: Downstream services that depend on `payments-api` via HTTP.

The fault: A broken ConfigMap is applied to `payments-api`, causing it to fail. All four downstream services degrade in cascade, triggering a storm of alerts that obscures the simple root cause.

Monitoring is wired via Prometheus ServiceMonitors and PrometheusRules with alerts on error rates, latency, queue depths, and resource usage across all five services.

### Key Paths

- `labs/alert-storm/README.md` -- scenario overview and components
- `labs/alert-storm/manifests/` -- Kubernetes manifests (namespace, deployments, ServiceMonitors, PrometheusRules)
- `labs/alert-storm/manifests/configmaps/` -- healthy and broken ConfigMap variants
- `labs/alert-storm/scripts/` -- shell scripts that implement each Make target
- `labs/alert-storm/images/` -- Dockerfiles and Python source for all five services

## Architecture: labs/image-pull-failure (Image Pull Failure with PDB Alert)

Single `inventory` namespace with one application:

- **`inventory-app`**: A simple service using Red Hat UBI (`registry.redhat.io/ubi9/ubi`) with 3 replicas. A PodDisruptionBudget requires at least 2 healthy pods.

The fault: A typo is introduced in the container image reference (`ubi9/ubi9` instead of `ubi9/ubi`), causing all pods to enter `ImagePullBackOff`. With zero healthy pods, the PDB is violated and the platform-level `PodDisruptionBudgetLimit` alert fires.

No custom images or PrometheusRules are needed; this scenario relies on a standard Red Hat image and the built-in OpenShift PDB alert.

### Key Paths

- `labs/image-pull-failure/README.md` -- scenario overview and components
- `labs/image-pull-failure/manifests/` -- Kubernetes manifests (namespace, deployment, service, ServiceMonitor, PDB)
- `labs/image-pull-failure/scripts/` -- shell scripts that implement each Make target

## Agent Skills

Agent-agnostic skills use the `.agents/skills/<skill-name>/SKILL.md` structure. Tool-specific symlinks point to each skill directory:

- `.claude/skills/<skill-name>` symlinks to `.agents/skills/<skill-name>` (Claude Code)

| Skill | Purpose |
|-------|---------|
| `review-scenario` | Audit a scenario for naming leaks, revealing comments, unrealistic faults |

## Tech Stack

- **Eval framework**: [lightspeed-evaluation](https://github.com/lightspeed-core/lightspeed-evaluation), Python 3.11+
- **System under test**: [OpenShift Lightspeed](https://github.com/openshift/lightspeed-service) (Agentic and Classic)
- **Applications** (labs scenarios): Python 3.12, FastAPI, raw psycopg2
- **Infrastructure**: OpenShift 4.x/5.x, Prometheus user workload monitoring
- **Deployment**: Raw Kubernetes YAML manifests via `oc apply`, no Helm/Kustomize
