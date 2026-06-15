##@ Lightspeed evaluation environment

.PHONY: setup-ols-evaluation
setup-ols-evaluation: venv/bin/activate ## Create venv and install lightspeed-evaluation

venv/bin/activate:
	@command -v python3 >/dev/null 2>&1 || \
	  { printf '\033[0;31mERROR:\033[0m python3 not found in PATH.\n'; exit 1; }
	@# lightspeed-evaluation requires Python >=3.11,<3.14 — prefer 3.13/3.12/3.11
	$(eval PYTHON := $(shell \
	  for v in python3.13 python3.12 python3.11; do \
	    command -v $$v 2>/dev/null && break; \
	  done))
	@[ -n "$(PYTHON)" ] || \
	  { printf '\033[0;31mERROR:\033[0m Python 3.11–3.13 required (lightspeed-evaluation does not support 3.14+).\n'; \
	    printf '  Install with: sudo dnf install python3.13\n'; exit 1; }
	@printf 'Using %s\n' "$(PYTHON)"
	$(PYTHON) -m venv venv
	venv/bin/pip install --quiet git+https://github.com/lightspeed-core/lightspeed-evaluation.git
	@printf '\033[0;32mDone.\033[0m venv ready at ./venv\n'

##@ Help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0,5) } \
	  /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2 }' \
	  $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
