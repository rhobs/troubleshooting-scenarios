SCRIPTS_DIR := $(realpath ../../scripts)

.PHONY: install-ossm check-ossm uninstall-ossm install-bookinfo setup-ossm help

install-ossm:
	@bash scripts/install-ossm-release.sh -c oc install-operators
	@bash scripts/install-ossm-release.sh -c oc -cpn istio-system install-istio

check-ossm:
	@bash scripts/install-ossm-release.sh status

install-bookinfo:
	@bash scripts/install-bookinfo.sh

uninstall-ossm:
	@OSSM_DELETE_CONFIRM=yes bash scripts/install-ossm-release.sh -c oc -cpn istio-system delete-istio
	@OSSM_DELETE_CONFIRM=yes bash scripts/install-ossm-release.sh -c oc -cpn istio-system delete-operators

setup-ossm: install-ossm install-bookinfo

help:
	@echo "Kiali/OSSM scenario helpers (eval targets are in the parent Makefile)"
	@echo ""
	@echo "  make install-ossm      Install OSSM operators + Istio + Kiali"
	@echo "  make check-ossm        Show OSSM/Sail/Kiali status"
	@echo "  make install-bookinfo  Install Bookinfo application"
	@echo "  make uninstall-ossm    Remove Istio/Kiali + operators"
	@echo "  make setup-ossm        Install OSSM + Bookinfo"
	@echo ""
	@echo "To run evals, from the parent directory:"
	@echo "  make setup-ols-classic"
	@echo "  make eval-ols-classic SCENARIO=kiali-ossm/check_mesh_status"
