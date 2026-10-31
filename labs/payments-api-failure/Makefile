.PHONY: help update-images deploy deploy-easy break fix cleanup delete-history break-redherring fix-redherring break-network fix-network

help:
	@echo "Payments API Failure Scenario"
	@echo ""
	@echo "Available targets:"
	@echo "  update-images     Build and push container images to quay.io/openshiftanalytics"
	@echo "  deploy            Deploy the initial state"
	@echo "  deploy-easy       Easy mode: single namespace, per-service DB users, fewer alerts, no red herring"
	@echo "  break             Roll out buggy reporting-service v1.0.2 and wait for failure"
	@echo "  fix               Roll back to reporting-service v1.0.1"
	@echo "  delete-history    Reset Prometheus TSDB and restart pods"
	@echo "  cleanup           Delete all demo resources"
	@echo "  break-redherring  Introduce red herring (CrashLoopBackOff)"
	@echo "  fix-redherring    Fix red herring"
	@echo "  break-network     Block egress from payments-api via NetworkPolicy"
	@echo "  fix-network       Remove the deny-all-egress NetworkPolicy"
	@echo ""
	@echo "Options:"
	@echo "  SINGLE_NAMESPACE=1  Deploy everything into the payments namespace"
	@echo "                      (only for deploy; deploy-easy always uses single namespace)"

update-images:
	@./scripts/update-images.sh $(REGISTRY)

deploy:
	@SINGLE_USER=1 SINGLE_NAMESPACE=$(SINGLE_NAMESPACE) ./scripts/deploy.sh

deploy-easy:
	@SINGLE_USER=0 SINGLE_NAMESPACE=1 ./scripts/deploy.sh

break:
	@./scripts/break.sh

fix:
	@./scripts/fix.sh

delete-history:
	@./scripts/delete-history.sh

cleanup:
	@./scripts/cleanup.sh

break-redherring:
	@./scripts/break-redherring.sh

fix-redherring:
	@./scripts/fix-redherring.sh

break-network:
	@./scripts/break-network.sh

fix-network:
	@./scripts/fix-network.sh
