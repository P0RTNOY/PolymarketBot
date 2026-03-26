# Polymarket ETH 15m Research Bot — Operations Guide

## Experiment status: **COLLECTING DATA** (v1 vs v2 A/B validation)

> **FROZEN PERIOD**
> During the 5–7 day data collection window, the following must NOT change:
> - Strategy logic (`bot/strategies/`)
> - Fill model settings (`FILL_MODEL_VERSION` in `experiment_config.py`)
> - Risk thresholds (`bot/core/config.py`)
> - Replay engine parameters (default `--seed 42 --runs 20`)
>
> **Bug fixes only.** Any config change requires re-running `make init-manifest`.

> [!IMPORTANT]
> **Data Baseline Note:** Due to Polymarket API changes, early collection data prior to the scanner fix is invalid. The clean, trustworthy **Phase 11.2 Experiment Data Collection Window strictly begins at:**
> **`2026-03-22 12:04 UTC`**
> Do not include any snapshots or signals prior to this timestamp in your rolling summaries.
---

## Local environment constraints

This stack runs **locally on your laptop**. There is no cloud hosting.

| If this happens… | Effect |
|---|---|
| Laptop sleeps | Data collection stops immediately |
| Docker quits | Data collection stops immediately |
| Container crashes | Container auto-restarts (≈5 s recovery) |
| `make down` | Stack stops; **database is preserved** |
| `make clean-volumes` | **ALL data wiped** — do not do this during experiment |

**Action required**: Disable automatic sleep on your MacBook:
> System Settings → Battery → Prevent automatic sleeping on power adapter when the display is off ✅
> Also: System Settings → Lock Screen → Start Screen Saver / Turn off display → set to "Never" or a long timeout

---

## One-time setup

```bash
# 1. Build the Docker images (only needed once, or after Dockerfile changes)
make build

# 2. Freeze the experiment configuration
make init-manifest

# 3. Start the stack
make up
```

Confirm everything is running:
```bash
make status   # all 5 containers should show "healthy" or "running"
make health   # API should return {"status": "ok"}
```

---

## File structure

```
polymarket_bot_scaffold/
├── results/
│   ├── manifests/
│   │   └── experiment_manifest.json      ← frozen config fingerprint
│   ├── daily/
│   │   ├── replay_2026-03-22.json        ← one file per day (full export)
│   │   └── replay_2026-03-22.csv         ← trade-level audit rows
│   ├── weekly/
│   │   └── replay_2026-03-22_to_2026-03-28.json
│   └── summaries/
│       └── daily_summary.csv             ← rolling multi-day summary
```

---

## Daily operating checklist

Do this **once per UTC day**, ideally in the morning:

- [ ] **Docker is running** — `make status` shows all containers up
- [ ] **Snapshots still accumulating** — `make last-snapshot-count` returns non-zero
- [ ] **No strategy files changed** — `git diff bot/strategies/ bot/core/config.py`
- [ ] **Run daily replay for yesterday**:
  ```bash
  make daily-report DATE=2026-03-22
  ```
- [ ] **Read the console summary** printed to terminal
- [ ] **Check rolling summary**:
  ```bash
  make summary
  ```
- [ ] **Do NOT modify strategy code** today

---

## Useful daily commands

```bash
# Start the full research stack
make up

# Check container status
make status

# Watch live worker logs
make logs

# Watch logs for a single service
make logs-scanner
make logs-paper_trader

# Check API health
make health

# Run daily replay (replace date)
make daily-report DATE=2026-03-22

# View rolling summary
make summary
```

---

## Weekly review (after 5–7 days)

Once you have 5–7 rows in `results/summaries/daily_summary.csv`, run:

```bash
# Aggregate replay over the full collection window
make weekly-report START=2026-03-22 END=2026-03-28
```

Then review `results/weekly/replay_2026-03-22_to_2026-03-28.json` and answer:

| Question | Where to look |
|---|---|
| Does v2 beat v1 on **mean** PnL? | `monte_carlo` section in JSON / CSV `mean_pnl` column |
| Does v2 beat v1 on **median** PnL? | `median_pnl` column — more robust than mean |
| Is v2's **downside tail** smaller? | `worst_pnl` column |
| Is the edge **robust across seeds**? | `pnl_stdev` — should be small relative to mean |
| Is v2 **actually better**, or just trading less? | Compare `filled_count` — if v2 fills are much fewer, it may just be more selective |
| Is performance **stable across days**? | Look at individual day rows in `daily_summary.csv` |

### Go-live decision rule

Do NOT proceed to live trading unless:
- [ ] v2 outperforms v1 on **both mean and median** PnL across 5+ days
- [ ] `pnl_stdev` is small relative to `mean_pnl` (robust, not lucky)
- [ ] `worst_pnl` is tolerable (drawdown acceptable)
- [ ] `fill_rate` is realistic (not 0%, not suspiciously high)
- [ ] Results are NOT driven by a tiny number of lucky trades

---

## Restarting cleanly after a laptop reboot

```bash
cd polymarket_bot_scaffold
make up
```

That is all. The database volume persists across reboots. The containers will
restart and pick up where they left off within a few seconds.

---

## Emergency stop and safe shutdown

```bash
make down          # stops containers, preserves database ✅
# DO NOT run:
make clean-volumes # this DELETES all collected data ❌
```

---

## Phase 12.0 — DB Migration (run once after upgrading)

Phase 12.0 adds 6 nullable columns to the `signals` table:
`alpha_score`, `exec_approved`, `exec_reasons`, `risk_approved`, `risk_reasons`, `features_json`.

All columns are nullable — existing rows are **not affected**.

### Local (SQLite — outside Docker)

```bash
# Preview only (no writes)
python scripts/migrate_120.py --dry-run

# Apply
python scripts/migrate_120.py
```

### Docker (DB inside container volume)

```bash
# Preview
docker compose exec api python scripts/migrate_120.py --dry-run

# Apply
docker compose exec api python scripts/migrate_120.py
```

> [!NOTE]
> The migration is **idempotent** — safe to run multiple times. Existing columns are skipped.

### Verify column population after migration

```bash
# Local
python scripts/check_120_columns.py

# Docker
docker compose exec api python scripts/check_120_columns.py
```

Expected output:
```
✅ alpha_score      : 0.06
✅ features_json    : 462 bytes, all 12 canonical keys present
✅ exec_approved    : None  (NULL is correct until Phase 12.2)
✅ Phase 12.0 column-population check complete.
```

### `features_json` canonical schema (stable from Phase 12.0)

Every `features_json` blob contains these keys (plus others):

| Key | Description |
|---|---|
| `market_prob` | Market-implied probability (midpoint) |
| `edge` | `model_prob - market_prob` as computed by the strategy |
| `spread` | `best_ask - best_bid` |
| `total_depth_usd` | Total visible USD depth (bid + ask) |
| `snapshot_age_ms` | Age of the snapshot in milliseconds |
| `depth_imbalance` | `(bid - ask) / total`; range −1 to +1 |
| `recent_movement` | `current.midpoint - previous.midpoint` |
| `minutes_to_expiry` | Estimated minutes until market resolves |

