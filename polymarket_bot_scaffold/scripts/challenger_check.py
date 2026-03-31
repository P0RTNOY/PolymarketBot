"""
Health check script for profile-specific challenger experiments.
Checks snapshot freshness, manifest integrity, and metadata presence.
"""
import argparse
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.core.paths import get_profile_manifest_path
from bot.core.market_profiles import get_profile
from bot.data.repositories.snapshots import SnapshotRepository
from bot.data.session import SessionLocal
from bot.data.models import Market
from sqlalchemy import select

def main():
    parser = argparse.ArgumentParser(description="Health check for a challenger experiment.")
    parser.add_argument("--profile", required=True, help="Market profile to check")
    args = parser.parse_args()
    
    print(f"\n{'='*65}")
    print(f" 🔍 CHALLENGER HEALTH CHECK: {args.profile.upper()}")
    print(f"{'='*65}")
    
    # 1. Check Manifest & Metadata
    manifest_path = get_profile_manifest_path(args.profile)
    metadata_path = manifest_path.parent / "challenger_metadata.json"
    
    manifest_exists = manifest_path.exists()
    metadata_exists = metadata_path.exists()
    
    print(f"  [Manifest]  : {'✅ EXISTS' if manifest_exists else '❌ MISSING'}")
    print(f"  [Metadata]  : {'✅ EXISTS' if metadata_exists else '❌ MISSING'}")
    
    if not manifest_exists:
        print(f"\n  ⚠️  WARNING: No manifest found for {args.profile}.")
        print(f"  Run 'make challenger-init PROFILE={args.profile}' first.")
        
    # 2. Check Snapshot Freshness
    print(f"\n  Snapshot Freshness ({args.profile}):")
    try:
        profile = get_profile(args.profile)
        
        # Resolve market IDs for this profile
        with SessionLocal() as session:
            all_markets = session.scalars(select(Market)).all()
            profile_market_ids = [m.id for m in all_markets if profile.matches(m)]
            
        repo = SnapshotRepository()
        latest = repo.get_latest_timestamp(market_ids=profile_market_ids)
        
        if latest:
            now = datetime.now(timezone.utc)
            # Ensure latest is timezone-aware for comparison
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            
            age = now - latest
            age_str = str(age).split('.')[0]
            
            status = "✅ FRESH" if age < timedelta(minutes=15) else "⚠️  DELAYED"
            print(f"    - Matching Markets : {len(profile_market_ids)}")
            print(f"    - Latest Snapshot  : {latest} ({age_str} ago) [{status}]")
        else:
            print(f"    - Matching Markets : {len(profile_market_ids)}")
            print("    - Latest Snapshot  : ❌ NONE FOUND (Active collection?)")
    except Exception as e:
        print(f"    - Latest Snapshot : ⚠️  Error checking: {e}")

    # 3. Check for Daily Reports
    daily_dir = manifest_path.parent.parent / "daily"
    if daily_dir.exists():
        recent_reports = sorted(list(daily_dir.glob("*.json")), reverse=True)[:3]
        print(f"\n  Recent Daily Reports ({len(list(daily_dir.glob('*.json')))} total):")
        for r in recent_reports:
            print(f"    - {r.name}")
    else:
        print(f"\n  Recent Daily Reports : ❌ NONE FOUND (Directory missing)")

    print(f"\n{'='*65}\n")

if __name__ == "__main__":
    main()
