import asyncio
from datetime import datetime, timezone
from bot.clients.polymarket_public import PolymarketPublicClient
from bot.data.repositories.markets import MarketRepository
from bot.data.repositories.snapshots import SnapshotRepository

async def main() -> None:
    client = PolymarketPublicClient()
    market_repo = MarketRepository()
    snapshot_repo = SnapshotRepository()
    
    print("[scanner] Starting Polymarket scanner loop...", flush=True)
    while True:
        try:
            print("[scanner] Fetching active markets...", flush=True)
            markets = await client.list_active_markets(limit=5)
            print(f"[scanner] Returning {len(markets)} active matching markets from API", flush=True)
            
            market_repo.upsert_many(markets)
            print(f"[scanner] stored {len(markets)} markets in DB", flush=True)

            for m in markets:
                tokens = m.get("tokens", [])
                yes_token = next((t for t in tokens if t.get("outcome", "").upper() == "YES"), None)
                if not yes_token:
                    continue
                
                token_id = yes_token.get("token_id")
                if not token_id:
                    continue
                
                book = await client.fetch_book(token_id)
                book["market_id"] = m["id"]
                book["timestamp"] = datetime.now(timezone.utc)
                snapshot_repo.insert_snapshot(book)
                
            print("[scanner] snapshot cycle complete")
            
        except Exception as e:
            print(f"[scanner] error: {e}")
            
        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
