COMPOSE ?= docker compose
PROFILE ?= eth_15m_direction
DATE    ?= $(shell date -v-1d +%Y-%m-%d)
START   ?= $(shell date -v-7d +%Y-%m-%d)
END     ?= $(shell date +%Y-%m-%d)
SEED    ?= 42
RUNS    ?= 20
LABEL   ?= research_exp_$(DATE)
BASELINE ?= eth_15m_direction
CHALLENGER ?= btc_1h_direction
DURATION ?= 7

.PHONY: help up down restart logs status health build \
        init-manifest daily-report weekly-report summary \
        challenger-init challenger-check compare-challenger \
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
	@$(COMPOSE) exec api python scripts/morning_check.py

monitor: ## Run morning-check in a continuous loop every 60 seconds
	@while true; do clear; $(MAKE) morning-check; echo ""; echo "Monitoring rig... (Ctrl+C to stop)"; sleep 60; done

# ── Research commands ─────────────────────────────────────────────────────────

init-manifest: ## Initialize research manifest
	@python3 scripts/generate_manifest.py \
		--label "$(LABEL)" \
		--seed $(SEED) \
		--runs $(RUNS) \
		--profile $(PROFILE)

challenger-init: ## Initialize a challenger experiment window
	@python3 scripts/init_challenger_experiment.py \
		--profile $(PROFILE) \
		--label "$(LABEL)" \
		--seed $(SEED) \
		--runs $(RUNS) \
		--duration $(DURATION)

daily-report: ## Run the daily replay for a specific UTC date (DATE=YYYY-MM-DD)
	@echo "  🔍  Running replay for date=$(DATE) seed=$(SEED) runs=$(RUNS)"
	@python3 scripts/run_daily_research.py \
		--date $(DATE) \
		--seed $(SEED) \
		--runs $(RUNS) \
		--profile $(PROFILE)

weekly-report: ## Run a multi-day replay (START and END in YYYY-MM-DD)
	@echo "  🔍  Running weekly replay from $(START) to $(END)"
	@python3 scripts/run_daily_research.py \
		--start $(START) \
		--end $(END) \
		--seed $(SEED) \
		--runs $(RUNS) \
		--profile $(PROFILE)

summary: ## Show the rolling daily summary CSV
	@echo "Last 14 days of research history ($(PROFILE)):"
	@python3 -c "import pandas as pd; \
	from bot.core.paths import get_profile_summary_path; \
	path = get_profile_summary_path('$(PROFILE)'); \
	print(pd.read_csv(path).tail(14).to_string(index=False)) if path.exists() else print('No summary found for $(PROFILE).')"

challenger-check: ## Health check for a challenger experiment
	@python3 scripts/challenger_check.py --profile $(PROFILE)

compare-challenger: ## Compare challenger vs baseline (START/END required)
	@python3 scripts/compare_market_profiles.py \
		--baseline $(BASELINE) \
		--challenger $(CHALLENGER) \
		--start $(START) \
		--end $(END)

# ── Danger zone ───────────────────────────────────────────────────────────────

clean-volumes: ## ⚠ DANGER: Delete the database volume (wipes all collected data)
	@read -p "This will DELETE ALL COLLECTED DATA. Are you sure? [y/N] " ans; \
	[ "$$ans" = "y" ] || { echo "Aborted."; exit 1; }
	$(COMPOSE) down -v
	@echo "  🗑   Volume deleted."
