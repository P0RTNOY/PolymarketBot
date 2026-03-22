from fastapi import APIRouter
from bot.core.config import get_settings

router = APIRouter()

@router.get("")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "app": s.app_name,
        "environment": s.app_env,
        "paper_trading_enabled": s.paper_trading_enabled,
        "live_trading_enabled": s.live_trading_enabled,
        "panic_stop": s.panic_stop,
    }
