EVAL_CMD_OPENAI = lightspeed-eval \
	--system-config system.yaml \
	--eval-data scenario_evals.yaml \
	--output-dir eval_output

EVAL_CMD_CLAUDE = lightspeed-eval \
	--system-config system.yaml \
	--eval-data scenario_evals_claude_vertex.yaml \
	--output-dir eval_output

SCENARIOS = oom envvar_missing batch_failure storage_binding readiness_probe_diagnosis namespace_pod_count scheduled_outage_detection periodic_failure_window config_drift_analysis ingress_rule_mismatch wrong_networkpolicy
SCENARIOS_CLAUDE = $(addsuffix -claude-vertex,$(SCENARIOS))

.PHONY: help all all-claude-vertex $(SCENARIOS) $(SCENARIOS_CLAUDE)

help:
	@echo "Usage: make <scenario>"
	@echo ""
	@echo "OpenAI scenarios:"
	@echo "  oom                        Run OOMKill diagnosis evaluation"
	@echo "  envvar_missing             Run missing env var CrashLoop evaluation"
	@echo "  batch_failure              Run job DB connection failure evaluation"
	@echo "  storage_binding            Run PVC misconfiguration evaluation"
	@echo "  readiness_probe_diagnosis  Run readiness probe failure evaluation"
	@echo "  namespace_pod_count        Run namespace pod counting evaluation"
	@echo "  scheduled_outage_detection Run scheduled outage detection evaluation"
	@echo "  periodic_failure_window    Run periodic failure window evaluation"
	@echo "  config_drift_analysis      Run config drift analysis evaluation"
	@echo "  ingress_rule_mismatch      Run NetworkPolicy ingress mismatch evaluation"
	@echo "  wrong_networkpolicy        Run NetworkPolicy frontend-backend blocking evaluation"
	@echo "  all                        Run all OpenAI scenarios"
	@echo ""
	@echo "Claude/Vertex AI scenarios (append -claude-vertex):"
	@echo "  oom-claude-vertex          Run OOMKill diagnosis with Claude on Vertex AI"
	@echo "  ...-claude-vertex          (same scenarios, Claude/Vertex provider)"
	@echo "  all-claude-vertex          Run all Claude/Vertex scenarios"

all: $(SCENARIOS)

all-claude-vertex: $(SCENARIOS_CLAUDE)

# OpenAI targets
$(SCENARIOS):
	$(EVAL_CMD_OPENAI) --tag $@

# Claude/Vertex targets — strip the -claude-vertex suffix to get the tag
$(SCENARIOS_CLAUDE):
	$(EVAL_CMD_CLAUDE) --tag $(subst -claude-vertex,,$@)
