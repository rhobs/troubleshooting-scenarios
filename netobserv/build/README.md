# NetObserv Installation

Installs the Network Observability operator and eval `FlowCollector` on OpenShift. Loki is deployed by the operator via `spec.loki.monolithic.installDemoLoki`. Requires an active cluster login before running any `make` target.

## Prerequisites

- `oc` configured and logged in: `oc login <cluster-api-url>`
- Cluster-admin privileges (OLM operator install)
- OpenShift 4.19+ recommended (`NetworkEvents` eBPF feature in eval `FlowCollector`)

---

## Automated setup

```bash
make setup-netobserv-openshift
```

What this does, step by step:

1. **Installs the NetObserv operator** via OLM (`install-netobserv-release.sh install-operator`).
2. **Applies the eval `FlowCollector`** from `build/flowcollector.yaml` (sampling 1, all eBPF features, MCP network policy allowances, `installDemoLoki: true`).
3. **Waits for `FlowCollector/cluster` Ready** — the operator deploys demo Loki and the pipeline in `spec.namespace`.

### Cleanup

```bash
make clean-netobserv-openshift
```

Removes the FlowCollector (and operator-managed demo Loki) plus operator Subscription/CSV (and the operator namespace when `NETOBSERV_DELETE_OPERATOR_NAMESPACE=yes`, the default).

### Troubleshooting OLM install

NetObserv only supports **All namespaces** install mode. If the Subscription fails with `UnsupportedOperatorGroup` / `OwnNamespace InstallModeType not supported`, patch or replace the OperatorGroup (no `targetNamespaces`):

```bash
oc apply -f - <<'EOF'
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: netobserv-operator-group
  namespace: openshift-netobserv-operator
spec:
  upgradeStrategy: Default
EOF
oc delete subscription netobserv-operator -n openshift-netobserv-operator --wait=true
make setup-netobserv-openshift
```

`install-netobserv-release.sh` applies this OperatorGroup automatically and removes a failed Subscription before recreating it.

### Customisation

| Variable | Default | Description |
|---|---|---|
| `NETOBSERV_NS` | `netobserv` | Pipeline namespace (`spec.namespace`) |
| `NETOBSERV_OPERATOR_NS` | `openshift-netobserv-operator` | OLM operator namespace |
| `NETOBSERV_CATALOG_SOURCE` | `redhat` | `redhat` or `community` (OpenShift marketplace) |
| `NETOBSERV_CHANNEL` | _(auto)_ | OLM channel (`stable` for redhat, `community` for community) |
| `NETOBSERV_FLOWCOLLECTOR_FILE` | `build/flowcollector.yaml` | FlowCollector manifest to apply |
| `NETOBSERV_FLOWCOLLECTOR_WAIT_TIMEOUT` | `10m` | `oc wait` timeout for FlowCollector Ready |

### Individual steps

```bash
make netobserv-install-operator      # Operator only
make netobserv-install-flowcollector # FlowCollector only (operator should exist)
make netobserv-status                # Operator, Loki, FlowCollector status
```

---

## Eval FlowCollector vs operator sample CR

Do **not** use `deploy-sample-cr` from netobserv-operator — its defaults are unsuitable for evals.

| Setting | Sample CR | Eval `flowcollector.yaml` |
|---------|-----------|---------------------------|
| `sampling` | 50 | 1 |
| `privileged` | false | true |
| eBPF features | commented out | DNSTracking, PacketDrop, FlowRTT, NetworkEvents |
| `networkPolicy.additionalNamespaces` | `[]` | `openshift-mcp` |
| `loki.monolithic.installDemoLoki` | commented out | `true` |

Scenario → required eBPF feature:

| Scenario | FlowCollector eBPF feature |
|----------|---------------------------|
| `dns_latency`, `dns_nxdomain` | `DNSTracking` |
| `packet_drops_kernel` | `PacketDrop` |
| `packet_drops_policy` | `NetworkEvents` |
| `tls_issues` | `NetworkEvents` |
| `tcp_rtt` | `FlowRTT` |

---

## Manual install from source (alternative)

For operator development or non-OLM clusters, install from the [netobserv-operator](https://github.com/netobserv/netobserv-operator) repository:

```bash
USER=netobserv make deploy
```

Then apply the eval FlowCollector (Loki is created by the operator when `installDemoLoki: true`):

```bash
make deploy-flowcollector
```

---

## MCP server

Eval scenarios use the **netobserv** toolset on **openshift-mcp-server**. The shared `eval.mk` infrastructure handles deployment automatically — running `make setup` from the `netobserv/` directory deploys the MCP server with `MCP_TOOLSETS=core,config,netobserv` and connects it to OLS.

See [`scripts/setup-mcp.sh`](../../scripts/setup-mcp.sh) and [`scripts/eval.mk`](../../scripts/eval.mk) for details.
