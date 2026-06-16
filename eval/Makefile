EVAL_CMD = lightspeed-eval \
	--system-config system.yaml \
	--eval-data scenario_evals.yaml \
	--output-dir eval_output

SCENARIOS = oom envvar_missing batch_failure storage_binding readiness_probe_diagnosis namespace_pod_count scheduled_outage_detection periodic_failure_window config_drift_analysis ingress_rule_mismatch wrong_networkpolicy

.PHONY: help all $(SCENARIOS)

help:
	@echo "Usage: make <scenario>"
	@echo ""
	@echo "Scenarios:"
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
	@echo "  all                        Run all scenarios"

all: $(SCENARIOS)

oom:
	$(EVAL_CMD) --tag oom

envvar_missing:
	$(EVAL_CMD) --tag envvar_missing

batch_failure:
	$(EVAL_CMD) --tag batch_failure

storage_binding:
	$(EVAL_CMD) --tag storage_binding

readiness_probe_diagnosis:
	$(EVAL_CMD) --tag readiness_probe_diagnosis

namespace_pod_count:
	$(EVAL_CMD) --tag namespace_pod_count

scheduled_outage_detection:
	$(EVAL_CMD) --tag scheduled_outage_detection

periodic_failure_window:
	$(EVAL_CMD) --tag periodic_failure_window

config_drift_analysis:
	$(EVAL_CMD) --tag config_drift_analysis

ingress_rule_mismatch:
	$(EVAL_CMD) --tag ingress_rule_mismatch

wrong_networkpolicy:
	$(EVAL_CMD) --tag wrong_networkpolicy
