SHELL := /bin/bash
COMPOSE := docker compose
DATE    ?= $(shell date -u +%Y-%m-%d)
START   ?= $(shell date -u -v-7d +%Y-%m-%d)
END     ?= $(shell date -u +%Y-%m-%d)
SEED    ?= 42
RUNS    ?= 20

.PHONY: help up down restart logs status health build \
        init-manifest daily-report weekly-report summary \
        last-snapshot-count morning-check clean-volumes

help: ## Show all available commands
	@echo ""
	@echo "  Polymarket ETH 15m Research Stack"
	@echo "  ══════════════════════════════════"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / \
		{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

# ── Stack management ─────────────────────────────────────────────────────────

build: ## Build Docker images (run once, or after Dockerfile/pyproject changes)
	$(COMPOSE) build

up: ## Start the full research stack (detached, auto-restart enabled)
	$(COMPOSE) up -d --remove-orphans
	@echo ""
	@echo "  ✅  Stack is running. Workers will begin collecting data."
	@echo "  📌  Keep the laptop POWERED ON and Docker RUNNING."
	@echo "  📌  Disable System Sleep in: System Settings → Battery → Prevent Automatic Sleep."
	@echo ""
	@$(COMPOSE) ps

down: ## Stop all containers (does NOT delete the database volume)
	$(COMPOSE) down
	@echo "  ⚠   Data collection stopped. Database volume is preserved."

restart: ## Restart all containers without rebuilding
	$(COMPOSE) restart

# ── Monitoring ────────────────────────────────────────────────────────────────

logs: ## Tail live logs from all services
	$(COMPOSE) logs -f

logs-%: ## Tail logs from a specific service, e.g. make logs-scanner
	$(COMPOSE) logs -f $*

status: ## Show container status and uptime
	$(COMPOSE) ps

health: ## Check the API health endpoint
	@curl -s http://localhost:8000/health | python3 -m json.tool || echo "API not reachable"

last-snapshot-count: ## Show how many market snapshots are stored in the DB
	@curl -s http://localhost:8000/snapshots/latest | python3 -m json.tool | head -20

morning-check: ## Run the daily morning health and status check
	@python3 scripts/morning_check.py

# ── Research commands ─────────────────────────────────────────────────────────

init-manifest: ## Freeze the experiment config (run ONCE before collecting data)
	@python3 scripts/generate_manifest.py \
		--label "eth_15m_v1v2_exp1_$(DATE)" \
		--seed $(SEED) \
		--runs $(RUNS)

daily-report: ## Run the daily replay for a specific UTC date (DATE=YYYY-MM-DD)
	@echo "  🔍  Running replay for date=$(DATE) seed=$(SEED) runs=$(RUNS)"
	@python3 scripts/run_daily_research.py \
		--date $(DATE) \
		--seed $(SEED) \
		--runs $(RUNS)

weekly-report: ## Run a multi-day replay (START and END in YYYY-MM-DD)
	@echo "  🔍  Running weekly replay from $(START) to $(END)"
	@python3 scripts/run_daily_research.py \
		--start $(START) \
		--end $(END) \
		--seed $(SEED) \
		--runs $(RUNS)

summary: ## Show the rolling daily summary CSV
	@if [ -f results/summaries/daily_summary.csv ]; then \
		echo ""; \
		echo "  Rolling research summary (results/summaries/daily_summary.csv):"; \
		echo ""; \
		column -t -s, results/summaries/daily_summary.csv; \
		echo ""; \
	else \
		echo "  No summary yet. Run 'make daily-report' first."; \
	fi

# ── Danger zone ───────────────────────────────────────────────────────────────

clean-volumes: ## ⚠ DANGER: Delete the database volume (wipes all collected data)
	@read -p "This will DELETE ALL COLLECTED DATA. Are you sure? [y/N] " ans; \
	[ "$$ans" = "y" ] || { echo "Aborted."; exit 1; }
	$(COMPOSE) down -v
	@echo "  🗑   Volume deleted."
