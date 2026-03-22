from fastapi import APIRouter
from bot.data.repositories.markets import MarketRepository

router = APIRouter()

@router.get("")
async def list_markets() -> dict:
    repo = MarketRepository()
    markets = repo.list_markets()
    return {"items": [m.raw_json or {"id": m.id, "question": m.question} for m in markets], "count": len(markets)}
