# Targets are limited by REQ-NF-07.
.DEFAULT_GOAL := help
.PHONY: help up down status health logs test import ops

help: ## list targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

up: ## build and start the app on http://localhost:8000
	docker compose up -d --build

down: ## stop the app
	docker compose down

status: ## show container status
	docker compose ps

health: ## GET /health from inside the container
	@docker compose exec -T app python -c "import urllib.request,json;print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8000/health')),indent=2))"

logs: ## follow the app logs
	docker compose logs -f app

test: ## pytest + ruff + docs links in the container (T=tests/x.py runs one file)
	docker compose run --rm -T -e LLM_MODE=mock app sh -c "pytest $(T) && ruff check . && python scripts/docs_links.py --check"

import: ## import the dataset: make import ZIP=../Dataset_Advogados_Jr_Completo.zip
	@test -n "$(ZIP)" || { echo "usage: make import ZIP=<path to dataset zip>"; exit 1; }
	docker compose run --rm -T -v "$(abspath $(ZIP)):/import/$(notdir $(ZIP)):ro" app python scripts/import_dataset.py /import/$(notdir $(ZIP))

ops: ## live ops dashboard of the agent loop on http://localhost:8001 (1 s refresh)
	@mkdir -p ops
	@docker rm -f tv-ops >/dev/null 2>&1 || true
	@docker run -d --name tv-ops -p 8001:8001 \
		-v "$(CURDIR)/scripts:/w/scripts:ro" -v "$(CURDIR)/ops:/w/ops:ro" -v "$(CURDIR)/docs/plan:/w/docs/plan:ro" \
		python:3.14-slim python /w/scripts/ops.py serve >/dev/null
	@echo "live ops: http://localhost:8001  (stop: docker rm -f tv-ops)"
