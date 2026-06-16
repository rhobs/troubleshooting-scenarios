# Kiali Installation

Installs Kiali on OpenShift via OpenShift Service Mesh (OSSM/Sail). Requires an active cluster login before running any `make` target.

## Prerequisites

- `oc` configured and logged in to the target cluster: `oc login <cluster-api-url>`

---

## OpenShift Service Mesh (OSSM / Sail)

Installs the Sail and Kiali operators via OLM, deploys an `Istio` CR and all add-ons, then installs Bookinfo using the official Kiali hack scripts and validates health through the Kiali API.

```bash
make setup-kiali-openshift
```

What this does, step by step:

1. **Installs operators** (Sail, Kiali) via `install-ossm-release.sh`.
2. **Installs Istio + addons + Kiali CR** in the control-plane namespace (`istio-system` by default).
3. **Waits for the Kiali deployment** to be created by the operator and becomes ready.
4. **Downloads Bookinfo hack scripts** from the Kiali repository (`KIALI_BOOKINFO_REF=master`).
5. **Downloads an Istio release tarball** (SHA-256 verified) for the Bookinfo installer (`BOOKINFO_ISTIO_VERSION=1.28.0`).
6. **Installs Bookinfo** with sidecar injection tied to the active `IstioRevisionTag`, and patches the traffic generator to use the in-cluster `productpage` URL.
7. **Validates health** by polling the Kiali API until `productpage-v1` reports `Healthy`.

### Cleanup

To remove everything installed by `setup-kiali-openshift`:

```bash
make clean-kiali-openshift
```

This deletes the Bookinfo namespace, OSSM Console namespace, control-plane namespace, operators, CSVs, and all Istio/Sail/ServiceMesh CRDs.

### Customisation

| Variable | Default | Description |
|---|---|---|
| `BOOKINFO_CP_NAMESPACE` | `istio-system` | Control-plane namespace |
| `BOOKINFO_NAMESPACE` | `bookinfo` | Bookinfo application namespace |
| `OSSM_ISTIO_PROFILE` | `default` | Istio CR profile passed to the install script |
| `KIALI_BOOKINFO_REF` | `master` | Kiali repo branch/tag for Bookinfo hack scripts |
| `BOOKINFO_ISTIO_VERSION` | `1.28.0` | Istio release used by the Bookinfo installer |
| `BOOKINFO_ISTIO_DIR` | _(empty)_ | Path to an existing Istio tree (skips download) |
| `KIALI_DEPLOYMENT_WAIT_MAX` | `600` | Seconds to wait for the Kiali deployment to appear |
| `BOOKINFO_KIALI_CLUSTER_NAME` | `Kubernetes` | Cluster name used in the Kiali API health check |

### Individual steps

The full `setup-kiali-openshift` flow can also be run in stages:

```bash
make ossm-install-operators          # Install Sail + Kiali operators only
make ossm-install-istio              # Install Istio CR + addons + Kiali CR only
make install-bookinfo-openshift      # Install Bookinfo only
make validate-bookinfo-kiali-health  # Run Kiali API health check only
```
