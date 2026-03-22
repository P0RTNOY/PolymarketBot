from fastapi import FastAPI
from apps.api.routes import health, markets, signals, positions, config, snapshots, paper
from bot.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(markets.router, prefix="/markets", tags=["markets"])
app.include_router(signals.router, prefix="/signals", tags=["signals"])
app.include_router(positions.router, prefix="/positions", tags=["positions"])
app.include_router(config.router, prefix="/config", tags=["config"])
app.include_router(snapshots.router, prefix="/snapshots", tags=["snapshots"])
app.include_router(paper.router, prefix="/paper", tags=["paper"])
