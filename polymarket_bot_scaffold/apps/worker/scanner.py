import asyncio
from datetime import datetime, timezone
from bot.clients.polymarket_public import PolymarketPublicClient
from bot.core.config import get_settings
from bot.core.market_profiles import get_profile
from bot.data.repositories.markets import MarketRepository
from bot.data.repositories.snapshots import SnapshotRepository

async def main() -> None:
    client = PolymarketPublicClient()
    market_repo = MarketRepository()
    snapshot_repo = SnapshotRepository()
    settings = get_settings()
    profile = get_profile(settings.market_profile)
    
    print(f"[scanner] Starting Polymarket scanner loop...", flush=True)
    print(f"[scanner] Active profile: {profile.name} ({profile.description})", flush=True)
    while True:
        try:
            print(f"[scanner] Fetching active markets for profile {settings.market_profile}...", flush=True)
            markets, total_checked = await client.list_active_markets(limit=5)
            print(f"[scanner] Checked {total_checked} active markets", flush=True)
            print(f"[scanner] Matched {len(markets)} markets for profile {settings.market_profile}", flush=True)
            
            market_repo.upsert_many(markets)
            print(f"[scanner] stored {len(markets)} markets in DB", flush=True)

            snapshot_attempts = 0
            snapshot_success = 0

            for m in markets:
                tokens = m.get("tokens", [])
                print(f"[scanner] Market {m.get('id')}: derived {len(tokens)} outcome tokens", flush=True)
                
                yes_token = next((t for t in tokens if t.get("outcome", "").upper() in ["YES", "UP", "ABOVE"]), None)
                if not yes_token and tokens:
                    yes_token = tokens[0] # Fallback to first outcome for binary markets
                
                if not yes_token:
                    continue
                
                token_id = yes_token.get("token_id")
                if not token_id:
                    continue
                
                try:
                    snapshot_attempts += 1
                    book = await client.fetch_book(token_id)
                    book["market_id"] = m["id"]
                    book["timestamp"] = datetime.now(timezone.utc)
                    snapshot_repo.insert_snapshot(book)
                    snapshot_success += 1
                except Exception as e:
                    print(f"[scanner] error fetching book for token {token_id}: {e}", flush=True)
                
            print(f"[scanner] snapshot cycle complete: attempted {snapshot_attempts}, written {snapshot_success}", flush=True)
            
        except Exception as e:
            print(f"[scanner] error: {e}")
            
        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
