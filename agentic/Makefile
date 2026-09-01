SCRIPTS_DIR := $(realpath ../scripts)

ALL_SCENARIOS := \
	blocked_deployment \
	blocked_deployment_alert \
	blocked_deployment_alert_remediation \
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
	orphaned_configmaps \
	orphaned_pvc \
	oversized_requests \
	partial_fix \
	pending_pvc_alert \
	pending_pvc_alert_remediation \
	pending_replicas \
	red_herring \
	refused_service \
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
SCENARIO ?=
TAG ?=
SETUP_MODE ?= run

COMMA := ,
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)

ifdef SCENARIO
  _CANDIDATES := $(strip $(subst $(COMMA), ,$(SCENARIO)))
else
  _CANDIDATES := $(ALL_SCENARIOS)
endif

ifdef TAG
  SCENARIOS := $(shell for d in $(_CANDIDATES); do \
    for t in $(subst $(COMMA), ,$(TAG)); do \
      grep -q '^    - '"$$t"'$$' $$d/evals.yaml 2>/dev/null && echo $$d && break; \
    done; \
  done)
else
  SCENARIOS := $(_CANDIDATES)
endif

.PHONY: setup eval cleanup help

setup:
	$(SCRIPTS_DIR)/setup-venv.sh
	@echo ""
	@echo "NOTE: Install lightspeed-agentic-operator manually by following:"
	@echo "  https://github.com/openshift/lightspeed-agentic-operator/tree/main/hack/quickstart"
	@echo "This will be automated in the future."

eval:
ifeq ($(SCENARIOS),)
	@echo "No scenarios match the given filters."
else
	@for scenario in $(SCENARIOS); do \
	  if [ ! -d "$$scenario" ]; then \
	    echo "Error: scenario '$$scenario' not found. Available scenarios:"; \
	    for d in */; do \
	      if [ -f "$$d/evals.yaml" ]; then echo "  $${d%/}"; fi; \
	    done; \
	    exit 1; \
	  fi; \
	done
	$(eval DATETIME := $(shell date +%Y%m%d_%H%M%S))
	$(eval EVAL_DIR := results/logs/$(DATETIME))
	$(eval _AGENTS := $(shell ../venv/bin/python3 -c "import yaml; c=yaml.safe_load(open('system.yaml')); print(' '.join(c.get('agents',{}).get('default',{}).get('agent',[])))"))
	$(eval _REPEAT := $(shell ../venv/bin/python3 -c "import yaml; c=yaml.safe_load(open('system.yaml')); print(c.get('agents',{}).get('default',{}).get('repeat',1))"))
ifeq ($(SETUP_MODE),run)
	@echo "==> SETUP_MODE=run: $(_REPEAT) repeat(s), agents: $(subst $(SPACE),$(COMMA) ,$(_AGENTS))"
	@for scenario in $(SCENARIOS); do \
	  for agent in $(_AGENTS); do \
	    for run in $$(seq 1 $(_REPEAT)); do \
	      echo ""; \
	      echo "==> Setup: $$scenario"; \
	      if [ -x $$scenario/setup.sh ]; then bash $$scenario/setup.sh; fi; \
	      bash $(SCRIPTS_DIR)/run-agentic-evals.sh \
	        --system-config system.yaml \
	        --evals $$scenario/evals.yaml \
	        --eval-dir $(EVAL_DIR) \
	        --agent $$agent \
	        --run-index $$run \
	        $(if $(TAG),--tags $(subst $(COMMA), ,$(TAG))); \
	      echo "==> Cleanup: $$scenario"; \
	      if [ -x $$scenario/cleanup.sh ]; then bash $$scenario/cleanup.sh || echo "WARNING: cleanup failed (non-fatal)"; fi; \
	    done; \
	  done; \
	done
else
	@echo "==> SETUP_MODE=scenario: $(_REPEAT) repeat(s), agents: $(subst $(SPACE),$(COMMA) ,$(_AGENTS))"
	@for scenario in $(SCENARIOS); do \
	  echo ""; \
	  echo "==> Setup: $$scenario"; \
	  if [ -x $$scenario/setup.sh ]; then bash $$scenario/setup.sh; fi; \
	  bash $(SCRIPTS_DIR)/run-agentic-evals.sh \
	    --system-config system.yaml \
	    --evals $$scenario/evals.yaml \
	    --eval-dir $(EVAL_DIR) \
	    $(if $(TAG),--tags $(subst $(COMMA), ,$(TAG))); \
	  echo "==> Cleanup: $$scenario"; \
	  if [ -x $$scenario/cleanup.sh ]; then bash $$scenario/cleanup.sh || echo "WARNING: cleanup failed (non-fatal)"; fi; \
	done
endif
	@echo ""
	@echo "==> Generating report..."
	@../venv/bin/python3 $(SCRIPTS_DIR)/generate-report-agentic.py \
	  $(EVAL_DIR) \
	  --output results/results_$(DATETIME).md
	@echo "==> Results: results/results_$(DATETIME).md"
endif

cleanup:
	@for scenario in $(SCENARIOS); do \
	  if [ -x $$scenario/cleanup.sh ]; then \
	    echo "==> Cleanup: $$scenario"; \
	    bash $$scenario/cleanup.sh; \
	  fi; \
	done
	rm -rf ../venv
	@echo "venv removed."

help:
	@echo "Usage: make <target> [SETUP_MODE=run|scenario]"
	@echo ""
	@echo "Targets:"
	@echo "  setup    Install venv (lightspeed-agentic-operator is manual for now)"
	@echo "  eval     Run all the $(words $(SCENARIOS)) scenarios"
	@echo "  cleanup  Run scenario cleanup scripts and remove venv"
	@echo "  help     Show this help"
	@echo ""
	@echo "Options:"
	@echo "  SCENARIO=...              Comma-separated scenario(s) to run (default: all)"
	@echo "  TAG=...                   Filter by tag (default: none)"
	@echo "  SETUP_MODE=run|scenario   Setup/cleanup lifecycle (default: run)"
	@echo "    run:      per (scenario, agent, repeat) - for mutating agents"
	@echo "    scenario: per scenario - for read-only agents, parallel OK"
	@echo ""
	@echo "Agents and repeat count are read from system.yaml."
	@echo ""
	@echo "Scenarios:"
	@echo "$(SCENARIOS)" | tr ' ' '\n' | column -x -c $$(tput cols) | expand | sed 's/^/  /'
