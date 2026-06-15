# Kiali Installation

Two installation paths are supported: **upstream** (vanilla Kubernetes/Kind via `istioctl`) and **OpenShift Service Mesh** (OSSM/Sail on OpenShift). Both require an active cluster login before running any `make` target.

## Prerequisites

- `kubectl` / `oc` configured and logged in to the target cluster
  - Upstream: `kubectl cluster-info`
  - OpenShift: `oc login <cluster-api-url>`

---

## Upstream (istioctl + vanilla Istio)

Installs Istio (demo profile) with Prometheus, Jaeger, and Kiali add-ons, then deploys the Bookinfo sample application and exposes both services locally via port-forward.

```bash
make setup-kiali
```

What this does, step by step:

1. **Downloads `istioctl`** (`ISTIO_VERSION=1.30.1`) into `_output/tools/bin/`.
2. **Installs Istio** (demo profile) and enables sidecar injection in the `default` namespace.
3. **Applies add-ons** — Prometheus, Kiali (`KIALI_VERSION=v2.27.0`), and Jaeger — into `istio-system`.
4. **Installs the Bookinfo demo** into a dedicated `bookinfo` namespace with the Istio ingress gateway.
5. **Exposes Kiali** on `http://localhost:20001`.
6. **Exposes Bookinfo** on `http://localhost:20002/productpage` and starts a background traffic generator.

### Customisation

| Variable | Default | Description |
|---|---|---|
| `ISTIO_VERSION` | `1.30.1` | Istio release to download and install |
| `KIALI_VERSION` | `v2.27.0` | Kiali image tag applied after operator install |

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
make ossm-install-operators   # Install Sail + Kiali operators only
make ossm-install-istio       # Install Istio CR + addons + Kiali CR only
make install-bookinfo-openshift  # Install Bookinfo only
make validate-bookinfo-kiali-health  # Run Kiali API health check only
```
