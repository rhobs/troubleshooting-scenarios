# scripts/eval.mk — shared eval infrastructure
# Include from suite Makefiles: include ../scripts/eval.mk

SCRIPTS_DIR := $(dir $(lastword $(MAKEFILE_LIST)))

# Defaults (teams override before include)

OLS_NS          ?= openshift-lightspeed
OLS_PORT        ?= 8443
OLS_URL         ?= https://localhost:$(OLS_PORT)
MCP_NS          ?= openshift-mcp
MCP_IMAGE       ?= registry.redhat.io/openshift-lightspeed/openshift-mcp-server-rhel9@sha256:8a8321cc2e00c3f13bf8e433da0fb3c990def939d5c7dec5f3978e9e323fc98b
MCP_DEPLOYMENT  ?= openshift-mcp-server
MCP_COMMAND     ?= /openshift-mcp-server
MCP_CONFIG_MOUNT ?= /etc/mcp
MCP_TOOLSETS    ?= core,config
MCP_KIALI_URL   ?=
MCP_OLS_NAME    ?= openshift-mcp
SYSTEM_CONFIG   ?= ./system.yaml
EVALS           ?= ./evals.yaml
RESULTS_DIR     ?= ./results
OLS_PROVIDER    ?=
OLS_MODEL       ?=

# Build optional --provider/--model flags for run-evals.sh
_PROVIDER_FLAGS = $(if $(OLS_PROVIDER),--provider $(OLS_PROVIDER)) $(if $(OLS_MODEL),--model $(OLS_MODEL))

# Shared setup (venv + preflight + OLS + MCP + connect)

.PHONY: _setup-shared
_setup-shared:
	@bash $(SCRIPTS_DIR)/setup-venv.sh
	@bash $(SCRIPTS_DIR)/preflight.sh
	@OPENAI_API_KEY="$(OPENAI_API_KEY)" OLS_NS=$(OLS_NS) \
	  bash $(SCRIPTS_DIR)/setup-ols.sh
	@MCP_NS=$(MCP_NS) MCP_DEPLOYMENT=$(MCP_DEPLOYMENT) MCP_IMAGE=$(MCP_IMAGE) \
	  MCP_COMMAND=$(MCP_COMMAND) MCP_CONFIG_MOUNT=$(MCP_CONFIG_MOUNT) \
	  MCP_TOOLSETS=$(MCP_TOOLSETS) MCP_KIALI_URL=$(MCP_KIALI_URL) \
	  bash $(SCRIPTS_DIR)/setup-mcp.sh
	@MCP_NS=$(MCP_NS) MCP_DEPLOYMENT=$(MCP_DEPLOYMENT) MCP_OLS_NAME=$(MCP_OLS_NAME) \
	  OLS_NS=$(OLS_NS) \
	  bash $(SCRIPTS_DIR)/connect-ols-mcp.sh

# Shared cleanup (disconnect + remove MCP; OLS stays)

.PHONY: _cleanup-shared
_cleanup-shared:
	@OLS_NS=$(OLS_NS) \
	  bash $(SCRIPTS_DIR)/disconnect-ols-mcp.sh
	@MCP_NS=$(MCP_NS) MCP_DEPLOYMENT=$(MCP_DEPLOYMENT) \
	  bash $(SCRIPTS_DIR)/cleanup-mcp.sh

# Run all scenarios

.PHONY: evals
evals:
	@bash $(SCRIPTS_DIR)/run-evals.sh \
	  --system-config $(SYSTEM_CONFIG) --evals $(EVALS) \
	  --results-dir $(RESULTS_DIR) --ols-url $(OLS_URL) \
	  $(_PROVIDER_FLAGS) \
	  --tags $(SCENARIOS)

# Auto-generated per-scenario targets

define _eval_target
.PHONY: $(1)-eval
$(1)-eval:
	@bash $(SCRIPTS_DIR)/run-evals.sh \
	  --system-config $(SYSTEM_CONFIG) --evals $(EVALS) \
	  --results-dir $(RESULTS_DIR) --ols-url $(OLS_URL) \
	  $(_PROVIDER_FLAGS) \
	  --tags $(1)
endef
$(foreach s,$(SCENARIOS),$(eval $(call _eval_target,$(s))))

# Run evals across all providers configured in the cluster's OLSConfig

.PHONY: evals-all-providers
evals-all-providers:
	@providers=$$(oc get olsconfig cluster -o jsonpath='{range .spec.llm.providers[*]}{.name},{.models[0].name}{"\n"}{end}'); \
	if [ -z "$$providers" ]; then \
	  echo "ERROR: No providers found in OLSConfig"; exit 1; \
	fi; \
	for entry in $$providers; do \
	  provider=$${entry%%,*}; \
	  model=$${entry##*,}; \
	  echo ""; \
	  echo "============================================"; \
	  echo "==> Provider: $$provider / $$model"; \
	  echo "============================================"; \
	  bash $(SCRIPTS_DIR)/run-evals.sh \
	    --system-config $(SYSTEM_CONFIG) --evals $(EVALS) \
	    --results-dir $(RESULTS_DIR)/$$provider --ols-url $(OLS_URL) \
	    --provider $$provider --model $$model \
	    --tags $(SCENARIOS); \
	done

# Help

.PHONY: help
help:
	@echo ""
	@echo "  make setup              Install venv + OLS + MCP + suite dependencies"
	@echo "  make evals              Run all scenarios"
	@$(foreach s,$(SCENARIOS),echo "  make $(s)-eval";)
	@echo "  make evals-all-providers  Run all scenarios across every configured provider"
	@echo "  make cleanup           Remove suite dependencies + MCP"
	@echo ""
	@echo "  OLS_URL=$(OLS_URL)  (override with OLS_URL=https://...)"
	@echo "  OLS_PROVIDER=          Override the LLM provider (e.g. google, anthropic)"
	@echo "  OLS_MODEL=             Override the LLM model (e.g. gemini-2.5-pro)"
	@echo ""
