# ─────────────────────────────────────────────────────────────────────────────
# Polymarket ETH 15m Research Bot — Makefile
# ─────────────────────────────────────────────────────────────────────────────

DATE     ?= $(shell date -u +%Y-%m-%d)
START    ?=
END      ?=
SEED     ?= 42
RUNS     ?= 20
MANIFEST ?= results/manifests/experiment_manifest.json

.PHONY: help up down logs status health db-init daily-report weekly-report \
        manifest manifest-show watch-summary clean-results

help:          ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Stack management ─────────────────────────────────────────────────────────

up:            ## Start the full research stack in detached mode
	@echo "▶  Starting research stack (detached)…"
	@mkdir -p data results/manifests results/daily results/weekly results/summaries
	docker compose up -d --build
	@echo "✅ Stack is up. Monitor with: make logs"

down:          ## Stop all containers (data and results are preserved)
	@echo "▶  Stopping research stack…"
	docker compose down
	@echo "✅ Containers stopped. Data on disk is safe."

restart:       ## Restart all containers without data loss
	docker compose restart

# ── Monitoring ───────────────────────────────────────────────────────────────

logs:          ## Stream combined logs from all containers
	docker compose logs -f --tail=100

logs-scanner:  ## Stream scanner logs only
	docker compose logs -f --tail=100 scanner

logs-signals:  ## Stream signal engine logs only
	docker compose logs -f --tail=100 signal_engine

logs-trader:   ## Stream paper trader logs only
	docker compose logs -f --tail=100 paper_trader

status:        ## Show container status summary
	@docker compose ps

health:        ## Hit the API health endpoint
	@curl -s http://localhost:8000/health | python3 -m json.tool

stats:         ## Show live paper stats from the API
	@curl -s http://localhost:8000/paper/stats | python3 -m json.tool

report:        ## Show today's daily report from the API
	@curl -s http://localhost:8000/paper/daily_report | python3 -m json.tool

# ── Database ─────────────────────────────────────────────────────────────────

db-init:       ## Manually initialise the database schema (auto-runs on 'up')
	docker compose exec api python -c \
	  "from bot.data.models import Base; from bot.data.session import engine; Base.metadata.create_all(engine)"

# ── Research workflow ─────────────────────────────────────────────────────────

manifest:      ## Create/refresh the frozen experiment manifest
	@read -p "Enter experiment label (e.g. eth_15m_v1v2_exp1): " LABEL; \
	python scripts/generate_manifest.py --label "$$LABEL" --seed $(SEED) --runs $(RUNS)

manifest-show: ## Display the current frozen experiment manifest
	@python scripts/generate_manifest.py --show

daily-report:  ## Run daily replay for DATE (default: today UTC). Usage: make daily-report DATE=2026-03-22
	@echo "▶  Running daily replay for $(DATE) …"
	python scripts/run_daily_research.py --date $(DATE) --seed $(SEED) --runs $(RUNS)

weekly-report: ## Run weekly replay for a date range. Usage: make weekly-report START=2026-03-22 END=2026-03-28
	@[ -n "$(START)" ] && [ -n "$(END)" ] || (echo "❌  Usage: make weekly-report START=YYYY-MM-DD END=YYYY-MM-DD" && exit 1)
	@echo "▶  Running weekly replay $(START) → $(END) …"
	python scripts/run_daily_research.py --start $(START) --end $(END) --seed $(SEED) --runs $(RUNS) \
	  --out results/weekly/replay_$(START)_to_$(END).json

watch-summary: ## Live-tail the rolling daily summary CSV
	@tail -f results/summaries/daily_summary.csv

# ── Housekeeping ─────────────────────────────────────────────────────────────

clean-results: ## Delete daily/weekly export files (keeps manifests and summary)
	@echo "▶  Removing results/daily/* and results/weekly/*"
	@rm -f results/daily/* results/weekly/*
	@echo "✅  Cleaned."
