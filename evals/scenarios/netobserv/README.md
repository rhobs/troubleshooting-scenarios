# NetObserv Evaluation Scenarios

Evaluation scenarios for AI-assisted diagnosis of OpenShift network observability problems. The scenarios use the `netobserv` MCP toolset and run with OLS-chat.

## Scenarios

| Scenario | Signal | Required feature |
|----------|--------|------------------|
| `dns_latency` | DNS latency in flow metrics and logs | `DNSTracking` |
| `dns_nxdomain` | NXDOMAIN and DNS failures | `DNSTracking` |
| `packet_drops_kernel` | Kernel packet drops | `PacketDrop` |
| `packet_drops_policy` | NetworkPolicy-related drops | `NetworkEvents`, `PacketDrop` |
| `tls_issues` | TLS and HTTPS connection errors | `NetworkEvents` |
| `tcp_rtt` | High TCP round-trip time | `FlowRTT` |

## Setup and running

All cases use `investigation` and `netobserv` tags. `packet_drops_kernel` and
`tls_issues` use `difficulty_medium`; the other cases use `difficulty_normal`.
See the [tag guide](../../README.md#tags) for filtering.

The evaluation installs the NetObserv operator and FlowCollector. It uses the
`netobserv` toolset in the built-in MCP server in OLS 2.0.1. The default
FlowCollector network policy allows access from `openshift-lightspeed`.

Run these commands from the repository root.

```bash
make setup-ols-chat

# All NetObserv scenarios
make eval-ols-chat TAG=netobserv

# One scenario
make eval-ols-chat SCENARIO=netobserv/dns_latency
```

The scenario setup scripts deploy synthetic traffic and wait for NetObserv data to reach Loki before the query runs. `NETOBSERV_WARMUP_SECS` controls the default 120-second warm-up.

To manage NetObserv independently, use its scenario Makefile:

```bash
make -C evals/scenarios/netobserv setup-netobserv-openshift
make -C evals/scenarios/netobserv netobserv-status
make -C evals/scenarios/netobserv clean-netobserv-openshift
```

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NETOBSERV_NS` | `netobserv` | NetObserv pipeline namespace |
| `NETOBSERV_OPERATOR_NS` | `openshift-netobserv-operator` | Operator namespace |
| `NETOBSERV_CATALOG_SOURCE` | `redhat` | OLM catalog source |
| `NETOBSERV_CHANNEL` | _(automatic)_ | OLM channel |
| `NETOBSERV_FLOWCOLLECTOR_WAIT_TIMEOUT` | `10m` | FlowCollector readiness timeout |
| `NETOBSERV_DELETE_OPERATOR_NAMESPACE` | `yes` | Delete the operator namespace during cleanup |
