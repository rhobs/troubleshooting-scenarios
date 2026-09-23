## Show available targets when no target is specified.
.DEFAULT_GOAL := help

##@ Linting

LINT_DIRS ?= evals labs scripts
TOOLS_VENV ?= .tools
TOOLS_PYTHON ?= python3
TOOLS_REQUIREMENTS := requirements-tools.txt
TOOLS_STAMP := $(TOOLS_VENV)/.installed

.PHONY: tools lint lint-shell lint-yaml

tools: $(TOOLS_STAMP) ## Install local development tools

$(TOOLS_STAMP): $(TOOLS_REQUIREMENTS)
	@command -v $(TOOLS_PYTHON) >/dev/null 2>&1 || \
	  { printf '\033[0;31mERROR:\033[0m %s not found.\n' "$(TOOLS_PYTHON)"; exit 1; }
	$(TOOLS_PYTHON) -m venv $(TOOLS_VENV)
	$(TOOLS_VENV)/bin/python -m pip install --quiet --requirement $(TOOLS_REQUIREMENTS)
	@touch $(TOOLS_STAMP)

lint: tools lint-shell lint-yaml ## Install tools and run all linters

lint-shell lint-yaml: tools

lint-shell: ## Lint shell scripts with shellcheck
	@files=$$(git ls-files --cached --others --exclude-standard -- $(LINT_DIRS) | \
	  awk '/\.sh$$/'); \
	if [ -z "$$files" ]; then \
	  printf 'No .sh files found in: %s\n' "$(LINT_DIRS)"; \
	else \
	  printf '==> shellcheck %s file(s)\n' "$$(echo "$$files" | wc -w)"; \
	  echo "$$files" | xargs $(TOOLS_VENV)/bin/shellcheck; \
	fi

lint-yaml: ## Lint YAML files with yamllint
	@files=$$(git ls-files --cached --others --exclude-standard -- $(LINT_DIRS) | \
	  awk '/\.ya?ml$$/'); \
	if [ -z "$$files" ]; then \
	  printf 'No YAML files found in: %s\n' "$(LINT_DIRS)"; \
	else \
	  printf '==> yamllint %s file(s)\n' "$$(echo "$$files" | wc -w)"; \
	  echo "$$files" | xargs $(TOOLS_VENV)/bin/yamllint -c .yamllint.yml; \
	fi

##@ Evals

SCRIPTS_DIR := scripts
SCENARIOS_DIR := evals/scenarios
EVALS_DIR := evals

_ALL_OLS_AGENTIC := \
	blocked_deployment \
	blocked_deployment_alert \
	blocked_deployment_alert_remediation \
	batch_submission_timeouts \
	blocked_dns \
	cascading_failure \
	crashlooping_pod_alert \
	crashlooping_pod_alert_remediation \
	degraded_namespace \
	destructive_resistance \
	diagnostic_trap \
	double_fault \
	empty_endpoints \
	evicted_pod \
	excessive_permissions \
	exhausted_quota \
	exhausted_quota_alert \
	exhausted_quota_alert_remediation \
	failed_job \
	failed_replicaset \
	failed_start \
	failing_api_alert \
	failing_api_alert_cross_namespace \
	failing_api_alert_cross_namespace_remediation \
	failing_api_alert_remediation \
	failing_init_container \
	failing_probe \
	failing_route \
	forbidden_api \
	imagepull_missing \
	imagepull_private \
	inactive_deployment \
	missing_configmap \
	missing_pvc \
	missing_secret_key \
	nothing_wrong \
	orphaned_configmaps \
	orphaned_pvc \
	oversized_requests \
	partial_fix \
	pending_pvc_alert \
	pending_replicas \
	red_herring \
	refused_connections \
	refused_service \
	restarting_pod_alert \
	stuck_rollout \
	stuck_rollout_alert \
	stuck_rollout_alert_remediation \
	timeout_connections \
	unbalanced_replicas \
	unknown_autoscaler \
	unknown_autoscaler_alert \
	unknown_autoscaler_alert_remediation \
	unprivileged_pod \
	unready_pod_alert \
	unready_pod_alert_remediation \
	unscheduled_pod
_ALL_OLS_CLASSIC := \
	batch_submission_timeouts \
	crashlooping_pod_alert \
	failed_job \
	failing_api_alert \
	failing_api_alert_cross_namespace \
	kiali-ossm/check_bookinfo_services \
	kiali-ossm/check_istio_objects_status \
	kiali-ossm/check_latency_bookinfo_issue \
	kiali-ossm/check_mesh_status \
	kiali-ossm/diagnose_bookinfo_fault_injection \
	kiali-ossm/diagnose_bookinfo_routing \
	kiali-ossm/troubleshoot_latency_trace \
	kubevirt/vm_crashloop \
	kubevirt/vm_migration_failure \
	kubevirt/vm_storage_failure \
	netobserv/dns_latency \
	netobserv/dns_nxdomain \
	netobserv/packet_drops_kernel \
	netobserv/packet_drops_policy \
	netobserv/tcp_rtt \
	netobserv/tls_issues \
	pending_pvc_alert \
	refused_connections \
	restarting_pod_alert \
	timeout_connections \
	unbalanced_replicas \
	unready_pod_alert
SCENARIO ?=
TAG ?=
AGENT ?=
SETUP_MODE ?= scenario
PREVIEW ?= 0

COMMA := ,
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)
_ALL_SCENARIOS := $(sort $(_ALL_OLS_AGENTIC) $(_ALL_OLS_CLASSIC))
_SCENARIO_LIST := $(strip $(subst $(COMMA), ,$(SCENARIO)))
_UNKNOWN_SCENARIOS := $(filter-out $(_ALL_SCENARIOS),$(_SCENARIO_LIST))

ifdef SCENARIO
  _OLS_AGENTIC_CANDIDATES := $(filter $(_ALL_OLS_AGENTIC),$(_SCENARIO_LIST))
  _OLS_CLASSIC_CANDIDATES := $(filter $(_ALL_OLS_CLASSIC),$(_SCENARIO_LIST))
else
  _OLS_AGENTIC_CANDIDATES := $(_ALL_OLS_AGENTIC)
  _OLS_CLASSIC_CANDIDATES := $(_ALL_OLS_CLASSIC)
endif

ifdef TAG
  OLS_AGENTIC_SCENARIOS := $(shell for d in $(_OLS_AGENTIC_CANDIDATES); do \
    for t in $(subst $(COMMA), ,$(TAG)); do \
      grep -q '^    - '"$$t"'$$' $(SCENARIOS_DIR)/$$d/evals-ols-agentic.yaml 2>/dev/null && echo $$d && break; \
    done; \
  done)
  OLS_CLASSIC_SCENARIOS := $(shell for d in $(_OLS_CLASSIC_CANDIDATES); do \
    for t in $(subst $(COMMA), ,$(TAG)); do \
      grep -q '^    - '"$$t"'$$' $(SCENARIOS_DIR)/$$d/evals-ols-classic.yaml 2>/dev/null && echo $$d && break; \
    done; \
  done)
else
  OLS_AGENTIC_SCENARIOS := $(_OLS_AGENTIC_CANDIDATES)
  OLS_CLASSIC_SCENARIOS := $(_OLS_CLASSIC_CANDIDATES)
endif

# A scenario can have eval definitions for either OLS Agentic, OLS Classic, or
# both. Standalone setup and cleanup targets use each selected scenario once.
MATCHED_SCENARIOS := $(sort $(OLS_AGENTIC_SCENARIOS) $(OLS_CLASSIC_SCENARIOS))

.PHONY: _validate-scenario-filters setup-scenario cleanup-scenario setup-venv setup-ols-agentic setup-ols-classic eval-ols-agentic eval-ols-classic cleanup-ols-agentic cleanup-ols-classic help

_validate-scenario-filters:
ifeq ($(strip $(SCENARIO)$(TAG)),)
	@echo "ERROR: set at least one filter: SCENARIO=... or TAG=..." >&2
	@exit 2
endif
ifneq ($(_UNKNOWN_SCENARIOS),)
	@echo "ERROR: unknown scenario name(s):" >&2
	@printf '  %s\n' $(_UNKNOWN_SCENARIOS) >&2
	@exit 2
endif
ifeq ($(MATCHED_SCENARIOS),)
	@echo "ERROR: no scenarios match the given filters." >&2
	@exit 2
endif

setup-scenario: _validate-scenario-filters
ifeq ($(PREVIEW),1)
	@echo "Preview only: no scenario setup or evaluation will run."
	@echo "Matched scenarios ($(words $(MATCHED_SCENARIOS))):"
	@printf '  %s\n' $(MATCHED_SCENARIOS)
else
	@bash $(SCRIPTS_DIR)/setup-scenarios.sh --scenarios $(MATCHED_SCENARIOS)
endif

cleanup-scenario: _validate-scenario-filters
ifeq ($(PREVIEW),1)
	@echo "Preview only: no scenario cleanup will run."
	@echo "Matched scenarios ($(words $(MATCHED_SCENARIOS))):"
	@printf '  %s\n' $(MATCHED_SCENARIOS)
else
	@bash $(SCRIPTS_DIR)/cleanup-scenarios.sh --scenarios $(MATCHED_SCENARIOS)
endif

setup-ols-agentic: setup-venv
	@venv/bin/python3 $(SCRIPTS_DIR)/sync-agent-crs.py $(EVALS_DIR)/system-ols-agentic.yaml
	@echo ""
	@echo "NOTE: Install lightspeed-agentic-operator manually by following:"
	@echo "  https://github.com/openshift/lightspeed-agentic-operator/tree/main/hack/quickstart"
	@echo "This will be automated in the future."

setup-venv:
	@$(SCRIPTS_DIR)/setup-venv.sh

setup-ols-classic: setup-venv
	@bash $(SCRIPTS_DIR)/preflight.sh
	@bash $(SCRIPTS_DIR)/setup-ols.sh

eval-ols-agentic:
ifeq ($(PREVIEW),1)
	@echo "Preview only: no setup, evaluation, or cleanup will run."
	@echo "SETUP_MODE: $(SETUP_MODE)"
	@echo "Agents:"
ifneq ($(AGENT),)
	@printf '  %s\n' $(subst $(COMMA), ,$(AGENT))
else
	@python3 -c "import yaml; c=yaml.safe_load(open('$(EVALS_DIR)/system-ols-agentic.yaml')); \
	  agents=c['agents']; \
	  [print('  ' + agents.get(a,{}).get('description',a)) for a in agents['default']['agent']]" \
	  2>/dev/null || echo "  (install PyYAML to resolve)"
endif
	@echo "Matched scenarios ($(words $(OLS_AGENTIC_SCENARIOS))):"
ifneq ($(OLS_AGENTIC_SCENARIOS),)
	@printf '  %s\n' $(OLS_AGENTIC_SCENARIOS)
else
	@echo "No scenarios match the given filters."
endif
else ifeq ($(OLS_AGENTIC_SCENARIOS),)
	@echo "No scenarios match the given filters."
else
	@if [ ! -x venv/bin/python3 ]; then \
	  echo "ERROR: Agent CRs may not be synchronized." >&2; \
	  echo "Run 'make setup-ols-agentic' before running evaluations." >&2; \
	  exit 1; \
	fi
	@venv/bin/python3 $(SCRIPTS_DIR)/sync-agent-crs.py --check $(EVALS_DIR)/system-ols-agentic.yaml
	@cd $(EVALS_DIR) && bash ../$(SCRIPTS_DIR)/eval-ols-agentic.sh \
	  --system-config system-ols-agentic.yaml \
	  --setup-mode $(SETUP_MODE) \
	  $(if $(AGENT),--agents $(subst $(COMMA), ,$(AGENT))) \
	  $(if $(TAG),--tags $(subst $(COMMA), ,$(TAG))) \
	  --scenarios $(addprefix scenarios/,$(OLS_AGENTIC_SCENARIOS)) \
	  || { status=$$?; if [ "$$status" -ne 64 ]; then exit "$$status"; fi; }
endif

eval-ols-classic:
ifeq ($(PREVIEW),1)
	@echo "Preview only: no setup, evaluation, or cleanup will run."
	@echo "SETUP_MODE: $(SETUP_MODE)"
	@echo "Agents:"
ifneq ($(AGENT),)
	@printf '  %s\n' $(subst $(COMMA), ,$(AGENT))
else
	@python3 -c "import yaml; c=yaml.safe_load(open('$(EVALS_DIR)/system-ols-classic.yaml')); \
	  agents=c['agents']; \
	  [print('  ' + agents.get(a,{}).get('description',a)) for a in agents['default']['agent']]" \
	  2>/dev/null || echo "  (install PyYAML to resolve)"
endif
	@echo "Matched scenarios ($(words $(OLS_CLASSIC_SCENARIOS))):"
ifneq ($(OLS_CLASSIC_SCENARIOS),)
	@printf '  %s\n' $(OLS_CLASSIC_SCENARIOS)
else
	@echo "No scenarios match the given filters."
endif
else ifeq ($(OLS_CLASSIC_SCENARIOS),)
	@echo "No OLS classic scenarios match the given filters."
else
	@cd $(EVALS_DIR) && bash ../$(SCRIPTS_DIR)/eval-ols-classic.sh \
	  --system-config system-ols-classic.yaml \
	  $(if $(TAG),--tags $(subst $(COMMA), ,$(TAG))) \
	  --scenarios $(addprefix scenarios/,$(OLS_CLASSIC_SCENARIOS))
endif

cleanup-ols-agentic:
	@rm -rf venv
	@echo "venv removed."
	@echo ""
	@echo "NOTE: Remove lightspeed-agentic-operator manually for now."
	@echo "This will be automated in the future."

cleanup-ols-classic: cleanup-ols-agentic
	@bash $(SCRIPTS_DIR)/cleanup-ols.sh

help: ## Show available targets
	@echo "Usage: make <target> [OPTIONS]"
	@echo ""
	@echo "Development:"
	@echo "  tools                Install local development tools"
	@echo "  lint                 Install tools and run all linters"
	@echo ""
	@echo "Setup:"
	@echo "  setup-scenario       Deploy selected scenario(s) in the cluster"
	@echo "  setup-ols-agentic    Install venv (OLS agentic operator is manual for now)"
	@echo "  setup-ols-classic    Install venv and OLS classic"
	@echo ""
	@echo "Evals:"
	@echo "  eval-ols-agentic     Run OLS agentic scenarios"
	@echo "  eval-ols-classic     Run OLS classic scenarios"
	@echo ""
	@echo "Cleanup:"
	@echo "  cleanup-scenario     Remove selected scenario(s)"
	@echo "  cleanup-ols-agentic  Remove venv (OLS agentic operator is manual for now)"
	@echo "  cleanup-ols-classic  Remove venv and OLS classic"
	@echo ""
	@echo "Options:"
	@echo "  SCENARIO=...              Comma-separated scenarios (required unless TAG is set)"
	@echo "  TAG=...                   Filter by tag (required unless SCENARIO is set)"
	@echo "  PREVIEW=1                 List matched scenarios without running them"
	@echo "  SETUP_MODE=run|scenario   Setup/cleanup lifecycle (default: scenario)"
	@echo "    run:      per (scenario, agent, repeat) - for mutating agents"
	@echo "    scenario: per scenario - for read-only agents, parallel OK"
	@echo ""
	@echo "Examples:"
	@echo "  make setup-scenario TAG=core"
	@echo "  make setup-scenario SCENARIO=blocked_deployment,failed_job"
	@echo "  make setup-scenario TAG=alert PREVIEW=1"
	@echo "  make cleanup-scenario SCENARIO=blocked_deployment,failed_job"
	@echo "  make cleanup-scenario TAG=alert PREVIEW=1"
	@echo "  make eval-ols-agentic TAG=core SETUP_MODE=scenario"
	@echo "  make eval-ols-agentic TAG=core PREVIEW=1"
	@echo "  make eval-ols-classic SCENARIO=crashlooping_pod_alert"
	@echo ""
	@echo "OLS agentic scenarios ($(words $(OLS_AGENTIC_SCENARIOS))):"
	@echo "$(OLS_AGENTIC_SCENARIOS)" | tr ' ' '\n' | column -x -c $$(tput cols) | expand | sed 's/^/  /'
	@echo ""
	@echo "OLS classic scenarios ($(words $(OLS_CLASSIC_SCENARIOS))):"
	@echo "$(OLS_CLASSIC_SCENARIOS)" | tr ' ' '\n' | column -x -c $$(tput cols) | expand | sed 's/^/  /'
