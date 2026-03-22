from __future__ import annotations
import httpx
from bot.core.config import get_settings

class PolymarketPublicClient:
    def _is_target_market(self, question: str) -> bool:
        q = question.lower()
        has_eth = "eth" in q or "ethereum" in q
        has_15 = "15m" in q or "15 min" in q or "15-min" in q or "15 minute" in q
        has_up_down = "up" in q or "down" in q or "above" in q or "below" in q
        return has_eth and has_15 and has_up_down

    async def list_active_markets(self, limit: int = 20) -> list[dict]:
        async with httpx.AsyncClient() as client:
            # Fetch a large batch to ensure we find our narrow target universe
            # using order=createdAt&ascending=false to get the NEWEST markets (15m markets exist here)
            res = await client.get(f"https://gamma-api.polymarket.com/markets?limit=500&active=true&closed=false&order=createdAt&ascending=false")
            res.raise_for_status()
            data = res.json()
            markets = data if isinstance(data, list) else data.get("data", [])
            
            import json
            result = []
            for m in markets:
                question = m.get("question", "")
                if not self._is_target_market(question):
                    continue

                outcomes_str = m.get("outcomes", "[]")
                clob_token_ids_str = m.get("clobTokenIds", "[]")
                try:
                    outcomes = json.loads(outcomes_str)
                    clob_token_ids = json.loads(clob_token_ids_str)
                except Exception:
                    outcomes = []
                    clob_token_ids = []
                    
                tokens = []
                if isinstance(outcomes, list) and isinstance(clob_token_ids, list):
                    for outcome, token_id in zip(outcomes, clob_token_ids):
                        tokens.append({"outcome": outcome, "token_id": str(token_id)})

                result.append({
                    "id": m.get("id") or m.get("condition_id", "unknown"),
                    "condition_id": m.get("condition_id"),
                    "question": m.get("question", ""),
                    "category": m.get("category", ""),
                    "active": m.get("active", True),
                    "closed": m.get("closed", False),
                    "tokens": tokens
                })
                if len(result) >= limit:
                    break
            return result

    async def fetch_book(self, token_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"https://clob.polymarket.com/book?token_id={token_id}")
            res.raise_for_status()
            data = res.json()

            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            best_bid = float(bids[0]["price"]) if bids else 0.0
            best_ask = float(asks[0]["price"]) if asks else 0.0
            midpoint = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.0
            spread = best_ask - best_bid if best_bid and best_ask else 0.0
            
            bid_depth_usd = sum(float(b["price"]) * float(b["size"]) for b in bids)
            ask_depth_usd = sum(float(a["price"]) * float(a["size"]) for a in asks)

            return {
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "midpoint": midpoint,
                "spread": spread,
                "bid_depth_usd": bid_depth_usd,
                "ask_depth_usd": ask_depth_usd,
            }
