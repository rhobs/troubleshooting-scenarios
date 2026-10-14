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
labs/             Fault scenarios for demos and manual troubleshooting
scripts/          Shared shell and Python tooling (venv, OLS, eval runners, reports, log capture)
Makefile          Orchestrates eval runs for OLS Agentic and OLS Classic
```

### Scenario structure

Most scenarios under `evals/scenarios/` are self-contained directories:

- `setup.sh` deploys fixtures to the cluster (creates namespaces, resources, faults)
- `cleanup.sh` removes everything the scenario created
- `fixtures/` contains the Kubernetes manifests applied by `setup.sh`
- `evals-*.yaml` contains eval definitions, one per tool under test (e.g. `evals-ols-agentic.yaml`, `evals-ols-classic.yaml`)

`kiali-ossm/`, `kubevirt/` and `netobserv/` are scenario *groups*: the parent directory holds `setup.sh`, `cleanup.sh`, a `Makefile`, `scripts/` and a `README.md` for the shared operator install and teardown, and each case lives in a nested directory with its own `setup.sh`, `cleanup.sh` and `evals-*.yaml`. `_disabled/` holds scenarios parked out of the run.

### Adding or modifying scenarios

When adding, removing, or renaming scenarios under `evals/scenarios/`, keep `evals/scenarios/README.md` (scenario table) and the root `Makefile` (scenario variables) in sync.

After adding or modifying a scenario, run the `review-scenario` skill. It checks for naming leaks, revealing comments, unrealistic fault setups and request-text leaks, and also verifies that each `conversation_group_id` matches the case directory name (or that name with a trailing `_alert` removed) and that every `evals-*.yaml` carries a `description:` block with `RCA:` and `Expected:` lines before `tag:`.

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

## Reading and debugging eval results

Each evaluation session has a directory under `evals/results/`, named
`YYYYMMDD_HHMMSS`. Use the session named by the user. If none is given, list the
session directories and check their saved config and progress to find the
relevant run. Results are gitignored, so inspect them directly on disk.

Paths below are relative to the session directory:

| Path | What to read |
|------|--------------|
| `report.md` | Overview of scenarios, agents, scores, responses, and errors. Updated during the session. |
| `progress.json` | Selected scenarios, agents, repeat count, setup mode, run states, failure details, and session exit code. |
| `system-ols-agentic.yaml` or `system-ols-classic.yaml` | Config saved for this session: models, judges, repeats, parallel setting, and metric thresholds. |
| `scenarios/<scenario>/evals-ols-*.yaml` | Saved eval definitions used by the session, including expected behavior and status checks. Group paths are kept. |
| `<agent>/run_N/*_summary.json` | Metric results and scores for repeat N. Match entries by `conversation_group_id` and `turn_id`. |
| `<agent>/run_N/*_detailed.csv` | Detailed metric output, including judge reasons when available. |
| `<agent>/run_N/*amended*.yaml` | Actual responses and recorded turn data. Agentic output also includes run status, phase results, and sandbox references. |
| `eval_report.json` | Framework report, when produced. Read it with the run files and progress data. |
| `logs/AGENTICRUN-PHASE.log` | Agentic sandbox container logs for `analysis`, `execution`, or `verification`. Duplicate filenames get `-1`, `-2`, etc. |
| `crs/KIND-NAME.yaml` | Full AgenticRun and result CR snapshots. Check result conditions and reasons for each phase, and parent UIDs to match the run. Agent and LLMProvider CRs are not saved. |
| `capture-logs.log` | Agentic watcher status and errors, including the mapping from pod names to log paths. |
| `failed-evals/output.*/` | Partial framework output saved after an evaluation failure, including files produced before agent/run directories existed. |

To investigate a result:

1. Read `report.md` and `progress.json` first. Check the session exit code and
   item details: a finished session can still contain failed evaluations.
2. Identify the scenario, agent, repeat, and turn. A `run_N` directory can hold
   output for several scenarios. Read all matching summary and amended files,
   rather than choosing only the first file or the newest timestamp.
3. Compare the actual response and metrics with the session's saved scenario
   definition and system config. Source files under `evals/scenarios/` may have
   changed since the run. Separate low judge scores from setup failures,
   evaluation errors, and failed AgenticRun completion checks.
4. For Agentic runs, read saved CRs under `crs/` when available. A result
   condition with `Completed=True` means the phase ended; check `reason`
   (`Succeeded`, `Failed`, or a timeout reason) for its outcome. CR snapshots
   are frozen at eval stop, recorded in `crs/eval-stops.json`. A framework
   timeout fails the eval even if the cluster run later completes. Otherwise,
   read `openshift_agentic_run_status` and
   `openshift_agentic_run_results` in the amended YAML. When present,
   `openshift_agentic_run_status.steps.<phase>.sandbox.claimName` gives the
   sandbox name. Search for it in `capture-logs.log` to find the matching log file,
   then read the phase logs for tool calls and errors.
5. If normal output is missing, inspect progress details, watcher diagnostics,
   and `failed-evals/`. Older sessions may lack snapshots or sandbox logs. The
   watcher skips pods present at startup, and a phase may never have started;
   a missing log alone does not prove that the application failed.
6. Report the evidence with file paths, scenario/turn IDs, agent, and repeat.
   Keep generated output in `evals/results/`. Promote reports to `evals/reports/`
   only when requested. See [the eval guide](evals/README.md) for report
   regeneration and scoring rules.

Automatic sandbox capture applies to `make eval-ols-agentic`. For manual
capture, start `./scripts/capture-logs --output-dir <directory>` before creating
AgenticRuns. Both use `capture_logs()` in `scripts/sandbox_logs.py`. Capture
errors are separate from the evaluation exit status; check `capture-logs.log`
when logs are missing.

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

The scenario uses a standard Red Hat image and the built-in OpenShift PDB alert. It also deploys the `inventory-alerts` PrometheusRule, which defines the `InventoryPodImagePullBackOff` warning alert with a `for: 30s` duration.

### Key Paths

- `labs/image-pull-failure/README.md` -- scenario overview and components
- `labs/image-pull-failure/manifests/` -- Kubernetes manifests (namespace, deployment, PDB, PrometheusRule)
- `labs/image-pull-failure/scripts/` -- shell scripts that implement each Make target

## Architecture: labs/control-plane-alerts (Control Plane Alerts)

Two independent faults affect existing cluster components:

- **Insights Operator**: The `insights-config` ConfigMap in `openshift-insights` overrides the upload endpoint with an incorrect URL, causing the operator to become degraded.
- **NTP (chronyd)**: On the first master node, `chronyd` is disabled and the clock is shifted forward by 2 minutes via `oc debug`, triggering time-synchronization alerts.

Run `make break` or `make fix` from the lab directory. The fix script deletes the ConfigMap override and re-enables `chronyd` so NTP can restore the clock. This lab operates on existing control-plane components and deploys no applications.

### Key Paths

- `labs/control-plane-alerts/README.md` -- fault descriptions and expected alerts
- `labs/control-plane-alerts/Makefile` -- break and fix targets
- `labs/control-plane-alerts/scripts/` -- scripts that introduce and revert the faults

## Agent Skills

Agent-agnostic skills use the `.agents/skills/<skill-name>/SKILL.md` structure. Tool-specific symlinks point to each skill directory:

- `.claude/skills/<skill-name>` symlinks to `.agents/skills/<skill-name>` (Claude Code)

| Skill | Purpose |
|-------|---------|
| `review-scenario` | Audit a scenario for naming leaks, revealing comments, unrealistic faults |

## Tech Stack

- **Eval framework**: [lightspeed-evaluation](https://github.com/lightspeed-core/lightspeed-evaluation), Python 3.11+
- **System under test**: [OpenShift Lightspeed](https://github.com/openshift/lightspeed-service) (Agentic and Classic)
- **Applications** (labs scenarios): Python 3.12, FastAPI and raw psycopg2 in `payments-api-failure`; Python 3.11 and Flask in `alert-storm`
- **Infrastructure**: OpenShift 4.x/5.x, Prometheus user workload monitoring
- **Deployment**: Raw Kubernetes YAML manifests via `oc apply`, no Helm/Kustomize
