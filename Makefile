# Targets are limited by REQ-NF-07; the rest is filled in T-01 (S0).
.DEFAULT_GOAL := help
.PHONY: help ops

help: ## list targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

ops: ## live ops dashboard of the agent loop on http://localhost:8001 (1 s refresh)
	@mkdir -p ops
	@docker rm -f tv-ops >/dev/null 2>&1 || true
	@docker run -d --name tv-ops -p 8001:8001 \
		-v "$(CURDIR)/scripts:/w/scripts:ro" -v "$(CURDIR)/ops:/w/ops:ro" -v "$(CURDIR)/docs/plan:/w/docs/plan:ro" \
		python:3.14-slim python /w/scripts/ops.py serve >/dev/null
	@echo "live ops: http://localhost:8001  (stop: docker rm -f tv-ops)"
