SCRIPTS_DIR := $(realpath ../../../scripts)

NETOBSERV_INSTALL_SCRIPT := $(abspath scripts/install-netobserv-release.sh)
NETOBSERV_NS ?= netobserv
NETOBSERV_OPERATOR_NS ?= openshift-netobserv-operator
KUBERNETES_CLI ?= oc
NETOBSERV_CATALOG_SOURCE ?= redhat
NETOBSERV_CHANNEL ?=
NETOBSERV_FLOWCOLLECTOR_FILE ?= $(abspath scripts/flowcollector.yaml)
NETOBSERV_FLOWCOLLECTOR_WAIT_TIMEOUT ?= 10m
NETOBSERV_DELETE_OPERATOR_NAMESPACE ?= yes

NETOBSERV_INSTALL_FLAGS = -c '$(KUBERNETES_CLI)' \
  -ns '$(NETOBSERV_NS)' \
  -ons '$(NETOBSERV_OPERATOR_NS)' \
  -cs '$(NETOBSERV_CATALOG_SOURCE)' \
  -fc '$(NETOBSERV_FLOWCOLLECTOR_FILE)'

ifneq ($(strip $(NETOBSERV_CHANNEL)),)
NETOBSERV_INSTALL_FLAGS += -ch '$(NETOBSERV_CHANNEL)'
endif

.PHONY: setup-netobserv-openshift netobserv-install-operator \
  netobserv-install-flowcollector netobserv-status clean-netobserv-openshift \
  setup-netobserv help

setup-netobserv-openshift:
	@test -f '$(NETOBSERV_INSTALL_SCRIPT)' || { echo "Missing $(NETOBSERV_INSTALL_SCRIPT)"; exit 1; }
	@echo "==> NetObserv: installing operator and FlowCollector (catalog=$(NETOBSERV_CATALOG_SOURCE)) ..."
	NETOBSERV_FLOWCOLLECTOR_WAIT_TIMEOUT='$(NETOBSERV_FLOWCOLLECTOR_WAIT_TIMEOUT)' \
	  bash '$(NETOBSERV_INSTALL_SCRIPT)' $(NETOBSERV_INSTALL_FLAGS) install
	@echo "==> setup-netobserv-openshift: done."

setup-netobserv: setup-netobserv-openshift

netobserv-install-operator:
	@test -f '$(NETOBSERV_INSTALL_SCRIPT)' || { echo "Missing $(NETOBSERV_INSTALL_SCRIPT)"; exit 1; }
	bash '$(NETOBSERV_INSTALL_SCRIPT)' $(NETOBSERV_INSTALL_FLAGS) install-operator

netobserv-install-flowcollector:
	@test -f '$(NETOBSERV_INSTALL_SCRIPT)' || { echo "Missing $(NETOBSERV_INSTALL_SCRIPT)"; exit 1; }
	NETOBSERV_FLOWCOLLECTOR_WAIT_TIMEOUT='$(NETOBSERV_FLOWCOLLECTOR_WAIT_TIMEOUT)' \
	  bash '$(NETOBSERV_INSTALL_SCRIPT)' $(NETOBSERV_INSTALL_FLAGS) install-flowcollector

netobserv-status:
	@test -f '$(NETOBSERV_INSTALL_SCRIPT)' || { echo "Missing $(NETOBSERV_INSTALL_SCRIPT)"; exit 1; }
	bash '$(NETOBSERV_INSTALL_SCRIPT)' $(NETOBSERV_INSTALL_FLAGS) status

clean-netobserv-openshift:
	@test -f '$(NETOBSERV_INSTALL_SCRIPT)' || { echo "Missing $(NETOBSERV_INSTALL_SCRIPT)"; exit 1; }
	@set -e; \
	flags='$(NETOBSERV_INSTALL_FLAGS)'; \
	echo "==> NetObserv: deleting FlowCollector ..."; \
	bash '$(NETOBSERV_INSTALL_SCRIPT)' $$flags delete-flowcollector; \
	echo "==> NetObserv: deleting operator ..."; \
	if [ '$(NETOBSERV_DELETE_OPERATOR_NAMESPACE)' = yes ]; then \
	  bash '$(NETOBSERV_INSTALL_SCRIPT)' $$flags -don delete-operator; \
	else \
	  bash '$(NETOBSERV_INSTALL_SCRIPT)' $$flags delete-operator; \
	fi; \
	echo "==> clean-netobserv-openshift: done."

help:
	@echo "NetObserv scenario helpers (eval targets are in the parent Makefile)"
	@echo ""
	@echo "  make setup-netobserv-openshift  Install operator + FlowCollector"
	@echo "  make netobserv-install-operator Install only the NetObserv operator"
	@echo "  make netobserv-install-flowcollector Apply the eval FlowCollector"
	@echo "  make netobserv-status           Show operator, Loki, and FlowCollector status"
	@echo "  make clean-netobserv-openshift  Remove FlowCollector and operator"
	@echo ""
	@echo "To run evals, from the parent agentic directory:"
	@echo "  make setup-ols-chat"
	@echo "  make eval-ols-chat SCENARIO=netobserv/dns_latency"
