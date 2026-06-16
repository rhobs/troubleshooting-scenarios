# Kiali / OSSM Troubleshooting Evaluation Scenarios

This directory contains evaluation scenarios that test how well an AI assistant — backed by an MCP server and an LLM — can diagnose and fix real service-mesh problems in a live cluster using Kiali.

---

## Prerequisites

### 1. Cluster login

You must be logged in to a running cluster before running any target.

- Kubernetes: `kubectl cluster-info`
- OpenShift: `oc login <cluster-api-url>`

### 2. MCP server with Kiali toolset

The AI assistant requires a running MCP server that exposes Kiali tools so it can query mesh topology, health, and Istio configuration objects.

| Platform | MCP server | Kiali toolset docs |
|---|---|---|
| Kubernetes | [`kubernetes-mcp-server`](https://github.com/containers/kubernetes-mcp-server) | [KIALI.md](https://github.com/containers/kubernetes-mcp-server/blob/main/docs/KIALI.md) |
| OpenShift | [`openshift-mcp-server`](https://github.com/openshift/openshift-mcp-server) | [KIALI.md](https://github.com/openshift/openshift-mcp-server/blob/main/docs/KIALI.md) |

Both servers use your existing kubeconfig credentials to authenticate Kiali API calls. Point the `[toolset_configs.kiali].url` in the server TOML to the Kiali route/service.

### 3. OpenShift Lightspeed (OLS)

The evaluation framework sends queries to an OLS instance as the system under test. See [openshift/lightspeed-service](https://github.com/openshift/lightspeed-service) for deployment instructions. The OLS endpoint is configured via `system.yaml` (`api.api_base`).

---

## Setup: install Istio, Kiali, and Bookinfo

All scenarios assume Istio, Kiali, and the Bookinfo sample application are already running in the cluster. See [`build/README.md`](build/README.md) for a full description of every step and all available variables.

```bash
make setup-kiali-openshift
```

Installs the Sail and Kiali operators via OLM, deploys an `Istio` CR with add-ons, installs Bookinfo using the Kiali hack scripts, and validates health through the Kiali API.

---

## Scenarios

Each scenario below corresponds to a conversation in [`evals.yaml`](evals.yaml) and an evaluation target in the [`Makefile`](Makefile). Scenarios with a `setup_script` introduce a fault before the conversation starts and clean it up afterwards.

### `check_mesh_status`

**Tag:** `check_mesh_status`

Asks the agent to perform a full mesh health assessment: control-plane version and health, observability stack status (Prometheus, Grafana, Tempo/Jaeger), and data-plane namespace health. The agent is expected to cite specific evidence from tool output and provide a prioritised action list.

```bash
make check_mesh_status-test
```

---

### `check_istio_objects_status`

**Tag:** `check_istio_objects_status`

A misconfigured `VirtualService` (`reviews-bad-config`) is deployed in `bookinfo` with four Kiali validation errors: missing gateway, undefined subset, non-existent destination host, and route weights not summing to 100. The agent must inspect Istio objects in the namespace and report each error with a concrete fix.

```bash
make check_istio_objects_status-test
```

---

### `fix_bookinfo_routing`

**Tag:** `fix_bookinfo_routing`

`reviews-v3` has weight 0 in the `reviews` VirtualService, so the product page never shows red stars. The agent must investigate the routing rules, identify the zero-weight subset, patch the VirtualService to distribute traffic to v3, and confirm the fix.

```bash
make fix_bookinfo_routing-test
```

---

### `fix_bookinfo_fault_injection`

**Tag:** `fault_injection_bookinfo`

A 100% fault-injection abort (HTTP 503) is applied to the `ratings` VirtualService, causing visible errors on the product page. All pods are running and mTLS is not the issue. The agent must find the abort rule, identify it as the root cause, and offer to remove it.

```bash
make fix_bookinfo_fault_injection-test
```

---

### `troubleshoot_latency_trace`

**Tag:** `troubleshoot_latency_trace`

A 3-second delay fault is injected on `ratings`, cascading latency across the entire Bookinfo call chain. The agent must use distributed traces or the Kiali traffic graph to pinpoint `ratings` as the responsible service, cite the `fixedDelay: 3s` VirtualService spec, and offer to remove the fault.

```bash
make troubleshoot_latency_trace-test
```

---

### `check_latency_bookinfo_issue`

**Tag:** `latency_bookinfo_issue`

Users report intermittent 5+ second load times on the product page. The agent must collect P95/P99 latency metrics, inspect the Kiali traffic graph, review distributed traces, and either identify an active root cause or — if no fault is currently active — provide actionable next steps (trace sampling, timeout/retry policies).

```bash
make check_latency_bookinfo_issue-test
```

---

### `check_bookinfo_services`

**Tag:** `check_bookinfo_services`

A general service-mesh health overview of the `bookinfo` namespace: namespace health status, per-service health and Istio config validity, and the traffic graph showing call paths, mTLS status, and response times.

```bash
make check_bookinfo_services-test
```

---

### `check_mesh_status` (no MCP / OLS only)

**Tag:** `no_kiali`

Same mesh-status question as the first scenario, but run against OLS **without** the Kiali/OSSM toolset. The agent must rely solely on Kubernetes-native tools (`kubectl`) to assess the control plane, observability stack, data plane, and Istio config objects.

```bash
make check_mesh_status-test-without-mcp
```

---

## Running all scenarios

The judge LLM requires an OpenAI API key. Export it before running any test target:

```bash
export OPENAI_API_KEY=<your-key>
```

Then run all MCP-enabled scenarios:

```bash
make test
```

This runs every MCP-enabled conversation in sequence. Results are written to `results/`.

---

## Evaluation framework

Scenarios are scored by a judge LLM (configured in [`system.yaml`](system.yaml)) using the `custom:answer_correctness` metric per turn. The framework is [`lightspeed-eval`](https://github.com/openshift/lightspeed-service); it is installed automatically into a local virtualenv when you run any `*-test` target.
