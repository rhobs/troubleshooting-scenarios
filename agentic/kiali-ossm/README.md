# Kiali/OSSM Evaluation Scenarios

Evaluation scenarios for AI-assisted diagnosis of OpenShift Service Mesh (OSSM) and Kiali problems. These scenarios deploy Bookinfo with Istio fault injections on a live cluster and evaluate OLS responses using the `ossm` MCP toolset. Currently OLS-classic only.

## Scenarios

| Scenario | Fault | Signal |
|----------|-------|--------|
| `check_mesh_status` | None (baseline) | Mesh health assessment |
| `check_istio_objects_status` | Misconfigured VirtualService with 4 validation errors | Kiali validation errors |
| `check_bookinfo_services` | None (baseline) | Namespace service health overview |
| `check_latency_bookinfo_issue` | None (intermittent user report) | Latency investigation |
| `diagnose_bookinfo_routing` | reviews-v3 weight=0, no red stars | Routing diagnosis |
| `diagnose_bookinfo_fault_injection` | 100% fault abort 503 on ratings | Fault injection diagnosis |
| `troubleshoot_latency_trace` | 3s fixedDelay on ratings | Trace-based latency diagnosis |

## Setup and Running

OSSM, Kiali, Bookinfo, MCP, and scenario fixtures are set up automatically when `eval-ols-classic` runs a kiali-ossm scenario (via `setup.sh` in this directory). From the parent `agentic/` directory:

```bash
make setup-ols-classic

# All kiali-ossm scenarios
make eval-ols-classic TAG=kiali-ossm

# Single scenario
make eval-ols-classic SCENARIO=kiali-ossm/check_mesh_status
```

To manage OSSM independently (from this directory):

```bash
make setup-ossm       # install OSSM + Bookinfo
make check-ossm       # show OSSM/Sail/Kiali status
make uninstall-ossm   # remove OSSM operators + Istio/Kiali
```

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_KIALI_URL` | `https://kiali.istio-system:20001/` | Kiali API URL for the MCP server |
| `MCP_TOOLSETS` | `core,config,ossm` | MCP toolsets to deploy |
| `KUBECTL` | `oc` | CLI tool (`oc` or `kubectl`) |
| `BOOKINFO_NAMESPACE` | `bookinfo` | Namespace for Bookinfo application |
| `BOOKINFO_ISTIO_VERSION` | `1.28.0` | Istio release version to download |
