# Polymarket ETH 15m Research Bot — Research Operating Guide

> **Phase**: 11.2 — Multi-day Validation (Frozen Experiment Window)
>
> **Objective**: Collect 5–7 days of live data to determine whether strategy v2 is genuinely better than v1 under realistic fill and risk assumptions.

---

## ⚠️ Critical: Local Environment Notice

**This system runs locally on your laptop.**

- The Docker containers collect data 24/7, but only while they are running.
- If the laptop sleeps, shuts down, or Docker stops → **data collection stops.**
- Disable sleep/hibernate on your machine for the duration of the experiment.
- There is no cloud or remote server. You are the server.

**macOS: Prevent sleep during experiment:**
```bash
# Keep the display off but prevent disk and system sleep
caffeinate -dims &
```

---

## Experiment Discipline Rules

During the 5–7 day collection window, **do not change any of the following:**

| What | Why |
|------|-----|
| Strategy files (`eth_direction_15m*.py`) | Changes invalidate comparisons |
| Risk manager settings (`config.py`, `.env`) | Alters approval rates mid-experiment |
| Fill model probability (currently 30%) | Changes PnL distribution |
| Replay engine logic | Makes today's data incompatible with day 1 |

**Bug fixes only.** If you fix a bug, re-run `make manifest` to re-freeze the config with the new hash.

---

## File Layout

```
polymarket_bot_scaffold/
├── docker-compose.yml          ← All 5 services defined here
├── Dockerfile                  ← Shared image for all services
├── Makefile                    ← All daily commands
├── .env                        ← Runtime config (git-ignored)
├── data/                       ← SQLite database (persistent, git-ignored)
├── results/
│   ├── manifests/
│   │   └── experiment_manifest.json   ← Frozen config fingerprint
│   ├── daily/
│   │   └── replay_YYYY-MM-DD.json     ← Per-day replay output
│   │   └── replay_YYYY-MM-DD.csv      ← Trade-level audit (same run)
│   ├── weekly/
│   │   └── replay_YYYY-MM-DD_to_YYYY-MM-DD.json
│   └── summaries/
│       └── daily_summary.csv          ← Rolling summary (one row per strategy per day)
└── scripts/
    ├── run_daily_research.py   ← Main daily entry point
    ├── generate_manifest.py    ← Freeze/show experiment config
    ├── replay_paper_day.py     ← Low-level replay engine
    ├── experiment_config.py    ← Config fingerprinting
    └── daily_summary.py        ← Rolling CSV + console printer
```

---

## First-Time Setup

```bash
cd polymarket_bot_scaffold

# 1. Create the data directory for persistent DB storage
mkdir -p data

# 2. Copy and fill in your environment file
cp .env.example .env
# Edit .env: set POLYMARKET_API_BASE and any API credentials if needed

# 3. Create the frozen experiment manifest (do this ONCE before starting)
make manifest
# → prompts for a label, e.g.: eth_15m_v1v2_exp1_march2026

# 4. Build and start the full stack
make up

# 5. Verify all containers are healthy
make status
make health
```

---

## Starting and Stopping the Stack

```bash
# Start (builds image if not already built):
make up

# View all container states:
make status

# Stream all logs:
make logs

# Stream a single service:
make logs-scanner
make logs-signals
make logs-trader

# Stop all containers (data is safe on disk):
make down

# Restart without data loss:
make restart
```

---

## Verify Data Is Being Collected

```bash
# Check the API health endpoint:
make health

# Check live paper trading stats:
make stats

# Check today's daily report (signals, fills, PnL):
make report

# Count snapshot rows in the database directly:
docker compose exec api python -c "
from bot.data.session import SessionLocal
from sqlalchemy import text
with SessionLocal() as s:
    n = s.execute(text('SELECT COUNT(*) FROM market_snapshots')).scalar()
    print(f'Snapshots in DB: {n}')
"
```

---

## Daily Research Checklist

Run this routine every morning (or once per completed UTC day):

```
┌─────────────────────────────────────────────────────────────────┐
│  DAILY RESEARCH CHECKLIST                                       │
├─────────────────────────────────────────────────────────────────┤
│  [ ] Docker Desktop is running                                  │
│  [ ] make status → all 5 containers show "Up"                  │
│  [ ] make health → API returns {"status":"ok"}                  │
│  [ ] make stats  → snapshot count is increasing vs yesterday   │
│  [ ] Run the daily replay for the completed UTC date:           │
│        make daily-report DATE=YYYY-MM-DD                        │
│  [ ] Read the console summary (v1 vs v2 side-by-side)           │
│  [ ] Open results/summaries/daily_summary.csv                   │
│        → confirm a new row was appended for each strategy       │
│  [ ] Note anything unusual in the rejection reasons             │
│  [ ] Do NOT modify any strategy, risk, or fill model files      │
└─────────────────────────────────────────────────────────────────┘
```

### Example daily command:
```bash
make daily-report DATE=2026-03-22
# Equivalent to:
python scripts/run_daily_research.py --date 2026-03-22 --seed 42 --runs 20
```

Output files saved to:
- `results/daily/replay_2026-03-22.json`
- `results/daily/replay_2026-03-22.csv`
- Row appended to `results/summaries/daily_summary.csv`

---

## Weekly Research Command

After collecting a full week:

```bash
make weekly-report START=2026-03-22 END=2026-03-28
# Equivalent to:
python scripts/run_daily_research.py --start 2026-03-22 --end 2026-03-28 --seed 42 --runs 20
```

Output: `results/weekly/replay_2026-03-22_to_2026-03-28.json`

---

## Viewing the Rolling Summary

The rolling summary is a CSV file that accumulates one row per strategy per replayed day:

```bash
# Tail it live:
make watch-summary

# Pretty-print in terminal:
column -t -s, results/summaries/daily_summary.csv | less -S

# Open in Excel/Numbers:
open results/summaries/daily_summary.csv
```

Key columns: `date`, `strategy_version`, `mean_pnl`, `median_pnl`, `best_pnl`, `worst_pnl`, `pnl_stdev`, `fill_rate_pct`, `win_rate_pct`, `settlement_mode`, `config_hash`

---

## Config Protection

The experiment is frozen via `results/manifests/experiment_manifest.json`.

If you modify any strategy or risk file by accident, the daily research script will warn you:

```
⚠  CONFIG MISMATCH — current hash (d15c28e1...) differs from manifest (8301b678...).
   Outputs will be written to a separate path to avoid contamination.
```

Outputs will be routed to `replay_YYYY-MM-DD_d15c28e1.json` instead of overwriting the clean data.

To check the current frozen config:
```bash
make manifest-show
```

---

## Weekly Review — Decision Framework

After 5–7 days of data, review `results/summaries/daily_summary.csv` and answer:

| Question | What to look at |
|----------|----------------|
| Does v2 beat v1 on mean PnL? | `mean_pnl` column per strategy |
| Does v2 beat v1 on median PnL? | `median_pnl` — more robust than mean |
| Is v2's downside better? | `worst_pnl` and `pnl_stdev` |
| Is performance stable across days? | Look at day-by-day `mean_pnl` — is it consistent? |
| Is v2 trading smarter or just less? | Compare `filled_count` + `win_rate_pct` |
| Are results robust across seeds? | Check `pnl_stdev` — low stdev = not luck-driven |

**Decision rule (conservative):**
> Go to v2 only if it beats v1 on **both mean and median PnL**, across **at least 5 days**, with **lower or equal stdev**, and **without a significantly worse fill rate**.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Container exits immediately | `make logs` → check for import errors or missing `.env` keys |
| No snapshots appearing | Check scanner logs: `make logs-scanner` |
| `make daily-report` shows 0 signals | Scanner may not have found matching ETH markets yet — normal for day 1 |
| Config mismatch warning | Run `make manifest-show` to see what changed |
| DB locked error | Only one process should write to SQLite; containers share the file via bind mount |

---

## Why the Laptop Must Stay On

This is a **local experiment**, not a cloud deployment. Every service in `docker-compose.yml` runs as a process on your machine. When the laptop sleeps:

1. Docker pauses or stops containers
2. The scanner stops fetching market snapshots
3. The signal engine stops generating signals
4. The paper trader stops simulating orders
5. There is no data for that time period — it is gone

**5–7 days of continuous data is the minimum requirement** for a trustworthy v1 vs v2 comparison. Any gaps in data reduce the reliability of conclusions.

Set your Mac to never sleep while plugged in:
> **System Settings → Battery → Prevent automatic sleeping on power adapter when the display is off → ON**

Or use `caffeinate` as described at the top of this guide.
