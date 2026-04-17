# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This repository contains reproducible OpenShift troubleshooting demo scenarios for teaching AI-assisted incident response. Each scenario deploys a realistic microservice environment, introduces a fault, and requires an AI assistant to diagnose the root cause.

## Repository Structure

Each top-level directory is an independent scenario with its own Makefile, manifests, application code, and scripts. Currently there is one scenario: `01-payments-api-failure/`.

## Working with Scenarios

All commands run from within a scenario directory (e.g., `cd 01-payments-api-failure/`).

### Prerequisites

- `oc login` to an OpenShift 4.x cluster

### Lifecycle Commands (via Make)

```bash
make deploy          # Deploy healthy state (single shared DB user)
make deploy-easy     # Deploy with per-service DB users (easier diagnosis)
make break           # Introduce the fault, wait for failure + alert
make fix             # Roll back to healthy state
make cleanup         # Delete all demo resources
make delete-history  # Reset Prometheus TSDB and restart pods
make break-redherring  # Add a red herring (CrashLoopBackOff)
make fix-redherring    # Remove the red herring
make break-network     # Block egress from payments-api via NetworkPolicy
make fix-network       # Remove the deny-all-egress NetworkPolicy
make update-images     # Rebuild and push container images to Quay.io
```

### Rebuilding Container Images

Run `make update-images` from the scenario directory. This builds from the Dockerfiles under `payments-api/` and `reporting-service/v1.0.*/` and pushes to Quay.io.

## Architecture: 01-payments-api-failure

Two OpenShift namespaces share a PostgreSQL database with `max_connections=20`:

- **`payments`** namespace: `payments-api` (Python/FastAPI) serves `GET /api/v1/process-payment` and runs a background traffic simulator. Connects cross-namespace to `postgres.shared-services.svc.cluster.local`.
- **`shared-services`** namespace: `postgres` (with postgres-exporter sidecar on port 9187), `reporting-service` (two versions), and `reconciliation-service` (intentional red herring, always in CrashLoopBackOff).

The fault: `reporting-service` v1.0.2 accumulates database connections without closing them, exhausting the shared pool and causing payments-api to return 503s from a different namespace.

Monitoring is wired via Prometheus ServiceMonitors and PrometheusRules with alerts on error rate (`PaymentErrorRateHigh`) and connection count (`PostgresqlConnectionsHigh`, `PostgresqlTooManyConnections`).

### Key Paths

- `01-payments-api-failure/CLAUDE.md` -- context given to the AI assistant performing the investigation (not a dev guide)
- `01-payments-api-failure/manifests/payments/` -- Kubernetes manifests for the payments namespace
- `01-payments-api-failure/manifests/shared-services/` -- Kubernetes manifests for the shared-services namespace
- `01-payments-api-failure/scripts/` -- shell scripts that implement each Make target
- `01-payments-api-failure/reporting-service/v1.0.1/` -- healthy version
- `01-payments-api-failure/reporting-service/v1.0.2/` -- buggy version (connection leak + division by zero)

## Tech Stack

- **Applications**: Python 3.12, FastAPI (payments-api), raw psycopg2 (reporting-service)
- **Infrastructure**: OpenShift 4.x, PostgreSQL 16, Prometheus user workload monitoring
- **Container images**: Built with Dockerfile, hosted on Quay.io
- **Deployment**: Raw Kubernetes YAML manifests applied via `oc apply`, no Helm/Kustomize
