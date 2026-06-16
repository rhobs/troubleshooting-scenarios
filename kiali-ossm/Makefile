# ──────────────────────────────────────────────────────────────────────────────
# scenarios/scenarios.mk  —  evaluation targets
#
# Included by the root Makefile. Variables defined there (OPENAI_KEY_FILE,
# GEMINI_KEY_FILE, …) are available here because include merges both files
# at parse time.
#
# All conversations are defined in scenarios/evals.yaml.
# Add a new conversation there, then optionally add an individual target below.
# ──────────────────────────────────────────────────────────────────────────────

include build/ossm.mk

SYSTEM_CONFIG = ./system.yaml
EVALS = ./evals.yaml
RESULTS_DIR = ./results

CLUSTER ?= openshift

ifeq ($(CLUSTER),kind)
  KUBECTL        ?= kubectl
  KIALI_ENDPOINT ?= http://localhost:20001/
  # Get a short-lived token from the kiali service account
  _AUTHTOKEN   = $(shell kubectl -n istio-system create token kiali --duration=8h 2>/dev/null)
else
  KUBECTL        ?= oc
  KIALI_ENDPOINT ?= https://kiali-istio-system.apps-crc.testing/
  _AUTHTOKEN   = $(shell oc whoami -t 2>/dev/null)
endif

EVAL_BASE = KUBECTL=$(KUBECTL) \
            KIALI_ENDPOINT=$(KIALI_ENDPOINT) \
			API_KEY=$(_AUTHTOKEN) \
            ../venv/bin/lightspeed-eval \
            --system-config $(SYSTEM_CONFIG) \
            --output-dir $(RESULTS_DIR) \
            --eval-data $(EVALS)

.PHONY: test test-without-mcp check_mesh_status-test

# ── all / test: run every conversation in evals.yaml ─────────────────────────
test:   check_mesh_status-test \
		check_istio_objects_status-test \
		check_bookinfo_services-test \
		check_latency_bookinfo_issue-test \
		fix_bookinfo_routing-test \
		fix_bookinfo_fault_injection-test \
		troubleshoot_latency_trace-test

test-without-mcp: check_mesh_status-test-without-mcp

# ── Individual conversation targets ───────────────────────────────────────────

fix_bookinfo_routing-test:
	$(EVAL_BASE) \
	  --tag fix_bookinfo_routing

fix_bookinfo_fault_injection-test:
	$(EVAL_BASE) \
	  --tag fault_injection_bookinfo

troubleshoot_latency_trace-test:
	$(EVAL_BASE) \
	  --tag troubleshoot_latency_trace

check_mesh_status-test:
	$(EVAL_BASE) \
	  --tag check_mesh_status

check_bookinfo_services-test:
	$(EVAL_BASE) \
	  --tag check_bookinfo_services

check_latency_bookinfo_issue-test:
	$(EVAL_BASE) \
	  --tag latency_bookinfo_issue

check_istio_objects_status-test:
	$(EVAL_BASE) \
	  --tag check_istio_objects_status

# No MCP Tests
check_mesh_status-test-without-mcp:
	$(EVAL_BASE) \
	  --tag no_kiali			