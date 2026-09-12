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
OLS_CLASSIC_SCENARIOS := \
	crashlooping_pod_alert \
	failed_job \
	failing_api_alert \
	failing_api_alert_cross_namespace \
	pending_pvc_alert \
	timeout_connections \
	unbalanced_replicas \
	unready_pod_alert
SCENARIO ?=
TAG ?=
AGENT ?=
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

_OLS_CLASSIC_CANDIDATES := $(filter $(_CANDIDATES),$(OLS_CLASSIC_SCENARIOS))
ifdef TAG
  _OLS_CLASSIC := $(shell for d in $(_OLS_CLASSIC_CANDIDATES); do \
    for t in $(subst $(COMMA), ,$(TAG)); do \
      grep -q '^    - '"$$t"'$$' $$d/evals-ols-classic.yaml 2>/dev/null && echo $$d && break; \
    done; \
  done)
else
  _OLS_CLASSIC := $(_OLS_CLASSIC_CANDIDATES)
endif

.PHONY: setup setup-ols-classic eval eval-ols-classic cleanup cleanup-ols-classic help

setup:
	$(SCRIPTS_DIR)/setup-venv.sh
	@echo ""
	@echo "NOTE: Install lightspeed-agentic-operator manually by following:"
	@echo "  https://github.com/openshift/lightspeed-agentic-operator/tree/main/hack/quickstart"
	@echo "This will be automated in the future."

setup-ols-classic: setup
	@bash $(SCRIPTS_DIR)/preflight.sh
	@bash $(SCRIPTS_DIR)/setup-ols.sh

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
ifdef AGENT
	$(eval _AGENTS := $(strip $(subst $(COMMA), ,$(AGENT))))
else
	$(eval _AGENTS := $(shell ../venv/bin/python3 -c "import yaml; c=yaml.safe_load(open('system.yaml')); print(' '.join(c.get('agents',{}).get('default',{}).get('agent',[])))"))
endif
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

eval-ols-classic:
ifeq ($(_OLS_CLASSIC),)
	@echo "No OLS classic scenarios match the given filters."
else
	$(eval DATETIME := $(shell date +%Y%m%d_%H%M%S))
	$(eval EVAL_DIR := results/logs/$(DATETIME))
	@for scenario in $(_OLS_CLASSIC); do \
	  if [ ! -f "$$scenario/evals-ols-classic.yaml" ]; then \
	    echo "Error: $$scenario/evals-ols-classic.yaml not found"; \
	    exit 1; \
	  fi; \
	done
	@bash $(SCRIPTS_DIR)/preflight.sh --require-ols
	@pf_pid=""; \
	eval_sa="ols-classic-eval"; \
	eval_sa_created=0; \
	eval_role_bound=0; \
	trap 'if [ -n "$$pf_pid" ]; then kill $$pf_pid 2>/dev/null || true; fi; if [ "$$eval_role_bound" -eq 1 ]; then oc adm policy remove-cluster-role-from-user cluster-reader -z "$$eval_sa" -n openshift-lightspeed >/dev/null 2>&1 || true; fi; if [ "$$eval_sa_created" -eq 1 ]; then oc delete serviceaccount "$$eval_sa" -n openshift-lightspeed --ignore-not-found >/dev/null 2>&1 || true; fi' EXIT; \
	if ! curl -ksf --connect-timeout 2 "https://localhost:8443/docs" >/dev/null 2>&1; then \
	  echo "==> Starting port-forward to OLS..."; \
	  oc port-forward -n openshift-lightspeed deployment/lightspeed-app-server 8443:8443 >/dev/null 2>&1 & \
	  pf_pid=$$!; \
	  ols_ok=false; \
	  for i in $$(seq 1 30); do \
	    if curl -ksf --connect-timeout 2 "https://localhost:8443/docs" >/dev/null 2>&1; then ols_ok=true; break; fi; \
	    sleep 2; \
	  done; \
	  if [ "$$ols_ok" != "true" ]; then \
	    echo "Error: OLS not reachable at https://localhost:8443 after port-forward attempt"; \
	    exit 1; \
	  fi; \
	fi; \
	auth_token=$$(oc whoami -t 2>/dev/null || true); \
	if [ -z "$$auth_token" ]; then \
	  echo "==> No OAuth token, creating service account token..."; \
	  if ! oc get serviceaccount "$$eval_sa" -n openshift-lightspeed >/dev/null 2>&1; then \
	    oc create serviceaccount "$$eval_sa" -n openshift-lightspeed >/dev/null; \
	    eval_sa_created=1; \
	  fi; \
	  if ! oc get clusterrolebinding -o jsonpath='{range .items[*]}{.roleRef.name}{"|"}{range .subjects[*]}{.kind}:{.namespace}:{.name}{" "}{end}{"\n"}{end}' 2>/dev/null \
	      | grep -q "^cluster-reader|.*ServiceAccount:openshift-lightspeed:$$eval_sa"; then \
	    oc adm policy add-cluster-role-to-user cluster-reader -z "$$eval_sa" -n openshift-lightspeed >/dev/null; \
	    eval_role_bound=1; \
	  fi; \
	  auth_token=$$(oc create token "$$eval_sa" -n openshift-lightspeed --duration=1h); \
	fi; \
	export API_KEY="$$auth_token"; \
	echo "==> Scenarios: $(_OLS_CLASSIC)"; \
	overall_status=0; \
	for scenario in $(_OLS_CLASSIC); do \
	  echo ""; \
	  echo "==> Setup: $$scenario"; \
	  scenario_status=0; \
	  if [ -x $$scenario/setup.sh ]; then bash $$scenario/setup.sh || scenario_status=$$?; fi; \
	  if [ $$scenario_status -eq 0 ]; then \
	    bash $(SCRIPTS_DIR)/run-agentic-evals.sh \
	      --system-config system-ols-classic.yaml \
	      --evals $$scenario/evals-ols-classic.yaml \
	      --eval-dir $(EVAL_DIR) \
	      $(if $(TAG),--tags $(subst $(COMMA), ,$(TAG))) || scenario_status=$$?; \
	  fi; \
	  echo "==> Cleanup: $$scenario"; \
	  if [ -x $$scenario/cleanup.sh ]; then bash $$scenario/cleanup.sh || echo "WARNING: cleanup failed (non-fatal)"; fi; \
	  if [ $$scenario_status -ne 0 ]; then overall_status=$$scenario_status; break; fi; \
	done; \
	if [ -n "$$(find "$(EVAL_DIR)" -name '*_summary.json' -print -quit 2>/dev/null)" ]; then \
	  echo ""; \
	  echo "==> Generating report..."; \
	  ../venv/bin/python3 $(SCRIPTS_DIR)/generate-report-classic.py \
	    $(EVAL_DIR) \
	    --output results/results_$(DATETIME).md || report_status=$$?; \
	  if [ $${report_status:-0} -eq 0 ]; then \
	    echo "==> Results: results/results_$(DATETIME).md"; \
	  elif [ $$overall_status -eq 0 ]; then \
	    overall_status=$$report_status; \
	  fi; \
	fi; \
	if [ $$overall_status -ne 0 ]; then exit $$overall_status; fi
endif

cleanup:
	@rm -rf ../venv
	@echo "venv removed."
	@echo ""
	@echo "NOTE: Remove lightspeed-agentic-operator manually for now."
	@echo "This will be automated in the future."

cleanup-ols-classic: cleanup
	@bash $(SCRIPTS_DIR)/cleanup-ols.sh

help:
	@echo "Usage: make <target> [SETUP_MODE=run|scenario]"
	@echo ""
	@echo "Targets:"
	@echo "  setup              Install venv (OLS agentic is manual for now)"
	@echo "  setup-ols-classic  Install venv and OLS classic"
	@echo "  eval               Run agentic scenarios ($(words $(SCENARIOS)) matched)"
	@echo "  eval-ols-classic   Run OLS classic scenarios ($(words $(_OLS_CLASSIC)) matched)"
	@echo "  cleanup            Remove venv (OLS agentic is manual for now)"
	@echo "  cleanup-ols-classic Remove venv and OLS classic"
	@echo "  help               Show this help"
	@echo ""
	@echo "Options (shared):"
	@echo "  SCENARIO=...              Comma-separated scenario(s) to run (default: all)"
	@echo "  TAG=...                   Filter by tag (default: none)"
	@echo ""
	@echo "Options (eval):"
	@echo "  AGENT=...                 Comma-separated agent model(s) to run (default: all from system.yaml)"
	@echo "  SETUP_MODE=run|scenario   Setup/cleanup lifecycle (default: run)"
	@echo "    run:      per (scenario, agent, repeat) - for mutating agents"
	@echo "    scenario: per scenario - for read-only agents, parallel OK"
	@echo "  Agents and repeat count are read from system.yaml.(agents can be overridden with AGENT=)."
	@echo "  Example: make eval AGENT=gpt-5.4,gemini-2.5-pro SCENARIO=blocked_deployment"
	@echo ""
	@echo "Options (eval-ols-classic):"
	@echo "  Agents and repeat count are read from system-ols-classic.yaml."
	@echo ""
	@echo "Agentic scenarios:"
	@echo "$(SCENARIOS)" | tr ' ' '\n' | column -x -c $$(tput cols) | expand | sed 's/^/  /'
	@echo ""
	@echo "OLS classic scenarios:"
	@echo "$(_OLS_CLASSIC)" | tr ' ' '\n' | column -x -c $$(tput cols) | expand | sed 's/^/  /'
