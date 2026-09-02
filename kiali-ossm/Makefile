# kiali-ossm evaluation scenarios

# Scenarios (must match tag: values in evals.yaml)
SCENARIOS = check_mesh_status \
            check_istio_objects_status \
            check_bookinfo_services \
            check_latency_bookinfo_issue \
            diagnose_bookinfo_routing \
            diagnose_bookinfo_fault_injection \
            troubleshoot_latency_trace

# Cluster platform
CLUSTER ?= openshift

ifeq ($(CLUSTER),kind)
  export KUBECTL        ?= kubectl
  export KIALI_ENDPOINT ?= http://localhost:20001/
else
  export KUBECTL        ?= oc
  export KIALI_ENDPOINT ?= https://kiali-istio-system.apps-crc.testing/
endif

# MCP config
MCP_TOOLSETS    = core,config,ossm
MCP_KIALI_URL  ?= https://kiali.istio-system:20001/

# Shared infrastructure
include ../scripts/eval.mk

# Team infrastructure (OSSM/Kiali/Bookinfo)
include build/ossm.mk

# Setup: shared infra + OSSM + Bookinfo
.PHONY: setup
setup: _setup-shared
	$(MAKE) setup-kiali-openshift

# Cleanup: Bookinfo + OSSM + shared infra
.PHONY: cleanup
cleanup:
	$(MAKE) clean-kiali-openshift
	$(MAKE) _cleanup-shared

# Without-MCP variant
.PHONY: check_mesh_status_no_kiali-eval
check_mesh_status_no_kiali-eval:
	@bash $(SCRIPTS_DIR)/run-evals.sh \
	  --system-config $(SYSTEM_CONFIG) --evals $(EVALS) \
	  --results-dir $(RESULTS_DIR) --ols-url $(OLS_URL) \
	  --tags check_mesh_status_no_kiali
