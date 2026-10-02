# KubeVirt Evaluation Scenarios

Evaluation scenarios for AI-assisted diagnosis of OpenShift Virtualization (KubeVirt) problems. These scenarios deploy broken VMs on a live cluster and evaluate OLS responses using the `kubevirt` MCP toolset. Currently OLS-classic only; agentic support is planned.

### KVM Requirements

OpenShift Virtualization requires KVM for VM execution. On cloud environments, only metal instance types expose `/dev/kvm`. When no KVM devices are detected, CNV install enables QEMU software emulation automatically. Scenarios that require a running VM (`vm_crashloop`, `vm_migration_failure`) are skipped if neither KVM nor emulation are available. The `vm_storage_failure` scenario always runs since the VM never reaches the scheduling phase.

## Scenarios

| Scenario | VM | Fault | Signal |
|----------|-----|-------|--------|
| `vm_storage_failure` | `production-db-vm` | Non-existent StorageClass `premium-nvme-storage` | VM stuck in `Provisioning` |
| `vm_crashloop` | `web-server-vm` | cloud-init `runcmd: shutdown -h now` | VM repeatedly starts and stops |
| `vm_migration_failure` | `critical-app-vm` | `nodeSelector` pins VM to one node | Live migration fails |

## Setup and Running

All cases use `investigation`, `kubevirt`, and `difficulty_normal` tags.
See the [tag guide](../../README.md#tags) for filtering.

CNV, MCP, and scenario fixtures are set up automatically when `eval-ols-classic` runs a kubevirt scenario (via `setup.sh` in this directory). If the CNV namespace already exists, the suite preserves that installation and does not change its emulation setting or uninstall it during cleanup. From the repository root:

```bash
make setup-ols-classic

# All kubevirt scenarios
make eval-ols-classic TAG=kubevirt

# Single scenario
make eval-ols-classic SCENARIO=kubevirt/vm_storage_failure
```

To manage CNV independently, use its scenario Makefile:

```bash
make -C evals/scenarios/kubevirt setup-cnv      # install + verify OpenShift Virtualization
make -C evals/scenarios/kubevirt require-kvm    # check KVM availability on worker nodes
make -C evals/scenarios/kubevirt uninstall-cnv  # remove OpenShift Virtualization
```

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NAMESPACE` | `kubevirt-scenarios` | Namespace for scenario VMs |
| `NODE_NAME` | First worker node | Node to pin migration VM to |
| `KUBECTL` | `oc` | CLI tool (`oc` or `kubectl`) |
| `CNV_NS` | `openshift-cnv` | Namespace of the OpenShift Virtualization installation |
