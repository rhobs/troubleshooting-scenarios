.PHONY: help update-images deploy break fix cleanup delete-history

help:
	@echo "Alert Storm Scenario"
	@echo ""
	@echo "Available targets:"
	@echo "  update-images     Build and push container images (REGISTRY=quay.io/...)"
	@echo "  deploy            Deploy the initial healthy state"
	@echo "  break             Trigger the alert storm and wait for cascade"
	@echo "  fix               Restore healthy state"
	@echo "  delete-history    Reset Prometheus TSDB and restart pods"
	@echo "  cleanup           Delete all demo resources"

update-images:
	@./scripts/update-images.sh $(REGISTRY)

deploy:
	@./scripts/deploy.sh

break:
	@./scripts/break.sh

fix:
	@./scripts/fix.sh

delete-history:
	@./scripts/delete-history.sh

cleanup:
	@./scripts/cleanup.sh
