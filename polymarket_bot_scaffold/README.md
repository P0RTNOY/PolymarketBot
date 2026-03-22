# Polymarket Bot Scaffold

Production-oriented Python starter for a **scanner + signal engine + paper trader + live execution service** targeting Polymarket-style binary markets.

## Included
- FastAPI control plane
- Async market scanner
- Strategy engine interface
- Paper trader skeleton
- Live executor skeleton
- SQLAlchemy models
- Risk manager
- Environment-driven settings
- Health endpoints
- Starter tests

## Current status
This is an MVP scaffold. It is intentionally safe-by-default:
- `LIVE_TRADING_ENABLED=false`
- `PAPER_TRADING_ENABLED=true`
- no private keys committed
- no real orders are placed unless you wire credentials and explicitly enable live mode

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn apps.api.main:app --reload
```

In another shell:

```bash
python -m apps.worker.scanner
python -m apps.worker.signal_engine
python -m apps.worker.paper_trader
```

## Suggested next steps
1. Wire real public market-data endpoints inside `bot/clients/polymarket_public.py`
2. Add migrations with Alembic
3. Implement WebSocket ingestion
4. Add realistic fill simulation
5. Add real authenticated execution only after paper results look good

## Safety notes
- Respect Polymarket regional/compliance restrictions and API terms.
- Keep all credentials server-side only.
- Treat this repo as research infrastructure, not guaranteed-profit trading software.
