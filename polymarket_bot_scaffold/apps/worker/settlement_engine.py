import asyncio
import httpx
from bot.data.session import SessionLocal
from bot.data.models import PaperPosition, Market
from bot.data.repositories.markets import MarketRepository
from datetime import datetime, timezone
from sqlalchemy import select

async def main() -> None:
    print("[settlement_engine] started")
    m_repo = MarketRepository()
    
    while True:
        try:
            unresolved_markets = m_repo.get_unresolved_markets()
            if not unresolved_markets:
                await asyncio.sleep(20)
                continue
                
            async with httpx.AsyncClient() as client:
                for market in unresolved_markets:
                    url = f"https://gamma-api.polymarket.com/markets/{market.id}"
                    try:
                        res = await client.get(url, timeout=10.0)
                        if res.status_code != 200:
                            continue
                            
                        data = res.json()
                        if data.get("closed") is True:
                            tokens = data.get("tokens", [])
                            winning_token = None
                            
                            for t in tokens:
                                if t.get("winner") is True or t.get("price") == 1.0:
                                    winning_token = t.get("token_id")
                                    break
                            
                            if winning_token:
                                # Mark formally resolved in the database
                                m_repo.mark_market_resolved(market.id, winning_token)
                                print(f"[settlement_engine] Market {market.id} resolved to Winner: {winning_token}")
                                
                                # Now cascade PnL to any OPEN positions linked to this market
                                with SessionLocal() as session:
                                    open_positions = session.scalars(select(PaperPosition).where(
                                        PaperPosition.market_id == market.id,
                                        PaperPosition.status == "OPEN"
                                    )).all()
                                    
                                    for pos in open_positions:
                                        if winning_token == pos.token_id:
                                            revenue = pos.size_shares * 1.0 # 100% payout
                                        else:
                                            revenue = 0.0 # 0% payout
                                            
                                        cost = pos.size_shares * pos.average_entry_price
                                        pnl = revenue - cost
                                        
                                        pos.status = "CLOSED"
                                        pos.closed_at = datetime.now(timezone.utc)
                                        pos.realized_pnl = pnl
                                        pos.outcome = "WIN" if revenue > 0 else "LOSS"
                                        
                                        print(f"[settlement_engine] Settled {pos.id} | Market {pos.market_id} | Outcome: {pos.outcome} | PnL: {pnl:.2f}")
                                    session.commit()
                                    
                    except Exception as req_ex:
                        print(f"[settlement_engine] Network error checking market {market.id}: {req_ex}")

            await asyncio.sleep(60)
        except Exception as e:
            print(f"[settlement_engine] ERROR: {e}")
            await asyncio.sleep(20)

if __name__ == "__main__":
    asyncio.run(main())
