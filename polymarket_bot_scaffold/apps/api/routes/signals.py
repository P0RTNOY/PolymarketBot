from fastapi import APIRouter
from bot.data.repositories.signals import SignalRepository

router = APIRouter()
repo = SignalRepository()

@router.get("/")
def list_signals():
    records = repo.get_latest_signals(limit=50)
    return {
        "status": "ok",
        "count": len(records),
        "items": [
            {
                "id": r.id,
                "strategy_name": r.strategy_name,
                "market_id": r.market_id,
                "token_id": r.token_id,
                "side": r.side,
                "market_prob": r.market_prob,
                "model_prob": r.model_prob,
                "edge": r.edge,
                "confidence": r.confidence,
                "suggested_price": r.suggested_price,
                "suggested_size_usd": r.suggested_size_usd,
                "reason": r.reason,
                "timestamp": r.timestamp
            } for r in records
        ]
    }
