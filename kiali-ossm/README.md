# Kiali / OSSM Troubleshooting Evaluation Scenarios

Evaluation scenarios that test how well an AI assistant — backed by an MCP server and an LLM — can diagnose and fix real service-mesh problems in a live cluster using Kiali.

## Prerequisites

- OpenShift cluster accessible via `oc login`
- `OPENAI_API_KEY` exported

## Quick start

```bash
export OPENAI_API_KEY=<your-key>
make setup     # install venv + OLS + MCP (ossm toolset) + OSSM/Kiali/Bookinfo
make evals     # run all scenarios
make cleanup  # remove Bookinfo + OSSM + MCP
```

`make setup` handles everything: venv creation, OLS operator install, MCP server deployment with the `ossm` toolset, and OSSM/Kiali/Bookinfo installation via [`build/ossm.mk`](build/ossm.mk). See [`build/README.md`](build/README.md) for details on OSSM variables and manual steps.

## Scenarios

Each scenario corresponds to a conversation in [`evals.yaml`](evals.yaml). Scenarios with a `setup_script` introduce a fault before the conversation and clean it up afterwards.

### `check_mesh_status`

Full mesh health assessment: control-plane version, observability stack status (Prometheus, Grafana, Tempo/Jaeger), and data-plane namespace health.

```bash
make check_mesh_status-eval
```

### `check_istio_objects_status`

A misconfigured `VirtualService` (`reviews-bad-config`) is deployed with four Kiali validation errors: missing gateway, undefined subset, non-existent destination host, and route weights not summing to 100.

```bash
make check_istio_objects_status-eval
```

### `diagnose_bookinfo_routing`

`reviews-v3` has weight 0 in the `reviews` VirtualService, so the product page never shows red stars. The agent should identify the zero-weight subset and describe the likely routing correction.

```bash
make diagnose_bookinfo_routing-eval
```

### `diagnose_bookinfo_fault_injection`

A 100% fault-injection abort (HTTP 503) on the `ratings` VirtualService. The agent should identify the abort rule as the root cause and explain what would restore normal service.

```bash
make diagnose_bookinfo_fault_injection-eval
```

### `troubleshoot_latency_trace`

A 3-second delay fault on `ratings`, cascading latency across the Bookinfo call chain. The agent must pinpoint `ratings` via traces or the Kiali traffic graph and cite the `fixedDelay: 3s` spec.

```bash
make troubleshoot_latency_trace-eval
```

### `check_latency_bookinfo_issue`

Intermittent 5+ second load times on the product page. The agent must collect latency metrics, inspect traces, and either identify an active root cause or provide actionable next steps.

```bash
make check_latency_bookinfo_issue-eval
```

### `check_bookinfo_services`

General service-mesh health overview of the `bookinfo` namespace: per-service health, Istio config validity, and the traffic graph.

```bash
make check_bookinfo_services-eval
```

### `check_mesh_status_no_kiali` (no MCP)

Same mesh-status question, but run against OLS **without** the Kiali/OSSM toolset. The agent must rely on Kubernetes-native tools only.

```bash
make check_mesh_status_no_kiali-eval
```

## Running all scenarios

```bash
export OPENAI_API_KEY=<your-key>
make evals
```

Results are written to `results/`.

To use a cluster Route instead of auto port-forward:

```bash
OLS_URL=https://<ols-route-host> make evals
```

## Evaluation framework

Scenarios are scored by a judge LLM (configured in [`system.yaml`](system.yaml)) using the `custom:answer_correctness` metric per turn. The framework is [`lightspeed-eval`](https://github.com/lightspeed-core/lightspeed-evaluation).
