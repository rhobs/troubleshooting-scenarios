SCRIPTS_DIR := $(realpath ../../scripts)

.PHONY: install-cnv check-cnv require-kvm uninstall-cnv setup-cnv help

install-cnv:
	@bash scripts/install-cnv.sh

check-cnv:
	@bash scripts/check-cnv.sh

require-kvm:
	@bash scripts/require-kvm.sh

uninstall-cnv:
	@bash scripts/uninstall-cnv.sh

setup-cnv: install-cnv check-cnv

help:
	@echo "KubeVirt scenario helpers (eval targets are in the parent Makefile)"
	@echo ""
	@echo "  make install-cnv    Install OpenShift Virtualization operator"
	@echo "  make check-cnv      Verify CNV is installed and ready"
	@echo "  make require-kvm    Check worker nodes have KVM devices"
	@echo "  make uninstall-cnv  Remove OpenShift Virtualization operator"
	@echo "  make setup-cnv      Install + verify CNV"
	@echo ""
	@echo "To run evals, from the parent directory:"
	@echo "  make setup-ols-classic"
	@echo "  make eval-ols-classic SCENARIO=kubevirt/vm_storage_failure"
