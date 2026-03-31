import asyncio
import argparse
import sys
from bot.clients.polymarket_public import PolymarketPublicClient
from bot.core.market_profiles import get_profile, ProfileMatcher, MARKET_PROFILES
from bot.core.config import get_settings

async def debug_profiles(profile_name: str, limit: int = 50):
    client = PolymarketPublicClient()
    settings = get_settings()
    
    # Override settings for this debug run if specified
    active_profile_name = profile_name or settings.market_profile
    print(f"--- Debugging Profile: {active_profile_name} ---")
    
    try:
        profile = get_profile(active_profile_name)
    except ValueError as e:
        print(f"Error: {e}")
        return

    matcher = ProfileMatcher(profile)
    
    # We want to see UNFILTERED markets to check the matches
    print(f"Fetching {limit} newest active markets...")
    import httpx
    async with httpx.AsyncClient() as hclient:
        res = await hclient.get(f"https://gamma-api.polymarket.com/markets?limit={limit}&active=true&closed=false&order=createdAt&ascending=false")
        res.raise_for_status()
        data = res.json()
        markets = data if isinstance(data, list) else data.get("data", [])

    print(f"Analyzing {len(markets)} markets...\n")
    
    matches_found = 0
    for m in markets:
        # Prepare tokens for matcher (gamma API format vs client format)
        # The client already handles token parsing, but here we have raw gamma data
        import json
        try:
            outcomes = json.loads(m.get("outcomes", "[]"))
            clob_ids = json.loads(m.get("clobTokenIds", "[]"))
            tokens = [{"outcome": o, "token_id": str(i)} for o, i in zip(outcomes, clob_ids)]
        except:
            tokens = []
        
        m_for_matcher = {
            "question": m.get("question", ""),
            "slug": m.get("slug", ""),
            "tokens": tokens
        }
        
        result = matcher.matches(m_for_matcher, explain=True)
        
        if result.matched:
            matches_found += 1
            print(f"✅ MATCH: {m_for_matcher['question']}")
            print(f"   Slug: {m_for_matcher['slug']}")
            print(f"   Passed: {', '.join(result.reasons_passed)}")
            print("-" * 40)
        else:
            # Print near-misses: matched asset but failed something else
            has_asset = any(ack.lower() in m_for_matcher['question'].lower() or ack.lower() in m_for_matcher['slug'].lower() for ack in profile.asset_keywords)
            if has_asset:
                print(f"❌ NEAR MISS: {m_for_matcher['question']}")
                print(f"   Failed: {', '.join(result.reasons_failed)}")
                print(f"   Detected Horizon: {result.detected_horizon_minutes}m")
                print(f"   Detected Direction: {result.detected_directional_terms}")
                print("-" * 40)

    print(f"\nSummary: Found {matches_found} matches for profile '{active_profile_name}' out of {len(markets)} checked.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=str, help="Profile name to test (default from config)")
    parser.add_argument("--limit", type=int, default=50, help="Number of markets to fetch")
    args = parser.parse_args()
    
    asyncio.run(debug_profiles(args.profile, args.limit))
