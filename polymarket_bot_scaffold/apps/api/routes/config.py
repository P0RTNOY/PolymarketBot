from fastapi import APIRouter
from bot.core.config import get_settings

router = APIRouter()

@router.get("")
def read_config() -> dict:
    s = get_settings()
    return {
        "min_edge": s.min_edge,
        "max_spread": s.max_spread,
        "min_depth_usd": s.min_depth_usd,
        "max_order_usd": s.max_order_usd,
        "max_market_exposure_usd": s.max_market_exposure_usd,
        "max_daily_loss_usd": s.max_daily_loss_usd,
    }
