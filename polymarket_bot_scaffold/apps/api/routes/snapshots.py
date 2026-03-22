from fastapi import APIRouter
from bot.data.repositories.snapshots import SnapshotRepository

router = APIRouter()

@router.get("")
async def list_snapshots(limit: int = 50) -> dict:
    repo = SnapshotRepository()
    snapshots = repo.get_latest_snapshots(limit=limit)
    items = []
    for s in snapshots:
        items.append({
            "id": s.id,
            "market_id": s.market_id,
            "token_id": s.token_id,
            "best_bid": s.best_bid,
            "best_ask": s.best_ask,
            "midpoint": s.midpoint,
            "spread": s.spread,
            "bid_depth_usd": s.bid_depth_usd,
            "ask_depth_usd": s.ask_depth_usd,
            "timestamp": s.timestamp.isoformat() if s.timestamp else None
        })
    return {"items": items, "count": len(items)}
