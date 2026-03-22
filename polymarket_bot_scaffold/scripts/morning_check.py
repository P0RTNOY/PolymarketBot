#!/usr/bin/env python3
"""
Morning check script for the Polymarket research stack.

Prints:
- All container states (via docker compose ps)
- Database snapshot stats (latest timestamp, count in the last hour)
- Whether yesterday's replay data has been generated yet
"""
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path so we can import bot modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.data.session import SessionLocal
from bot.data.models import MarketSnapshot
from sqlalchemy import select, func


def check_containers():
    print("🐳 Checking Docker containers...")
    try:
        # Run docker compose ps and print output
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "table {{.Service}}\t{{.State}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            check=True
        )
        # Prettify the output slightly
        lines = result.stdout.strip().split('\n')
        if not lines or len(lines) <= 1:
            print("  ⚠  No containers are currently running. Did you run `make up`?")
        else:
            for line in lines:
                print(f"  {line}")
    except FileNotFoundError:
        print("  ℹ  Skipping container check (running inside Docker wrapper).")
        print("     Use `make status` on the host machine to see container states.")
    except subprocess.CalledProcessError as e:
        print("  ❌  Failed to get container status:")
        print(f"      {e.stderr.strip()}")
    print()


def check_database():
    print("📊 Checking database snapshots...")
    try:
        with SessionLocal() as db:
            # Get the latest snapshot timestamp
            stmt_latest = select(func.max(MarketSnapshot.timestamp))
            latest_ts = db.execute(stmt_latest).scalar()

            if not latest_ts:
                print("  ⚠  No snapshots found in the database yet.")
                return

            # Count snapshots in the last hour
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            stmt_count = select(func.count(MarketSnapshot.id)).where(MarketSnapshot.timestamp >= one_hour_ago)
            count_last_hour = db.execute(stmt_count).scalar()

            # Ensure latest_ts is timezone aware for formatting
            if latest_ts.tzinfo is None:
                latest_ts = latest_ts.replace(tzinfo=timezone.utc)
            
            # Calculate how long ago the latest snapshot was
            now = datetime.now(timezone.utc)
            delta = now - latest_ts
            minutes_ago = int(delta.total_seconds() / 60)

            print(f"  📸 Latest snapshot:  {latest_ts.strftime('%Y-%m-%d %H:%M:%S UTC')} ({minutes_ago} mins ago)")
            print(f"  📈 Last hour count:  {count_last_hour} snapshots collected")
            
            if minutes_ago > 15:
                print("  ⚠  WARNING: The latest snapshot is more than 15 minutes old.")
                print("     Check `make logs-scanner` to ensure data collection is still running.")
            elif count_last_hour == 0:
                print("  ⚠  WARNING: No snapshots collected in the last hour.")
            else:
                print("  ✅  Data collection appears healthy.")
            
    except Exception as e:
        print(f"  ❌  Failed to query database: {e}")
    print()


def check_replay_status():
    print("🔄 Checking yesterday's replay status...")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    yesterday_str = yesterday.isoformat()
    
    # Check for both standard and config-mismatched files
    daily_dir = Path("results/daily")
    if not daily_dir.exists():
        print(f"  ❌  results/daily directory does not exist.")
        return

    # Find files starting with replay_{yesterday}
    files = list(daily_dir.glob(f"replay_{yesterday_str}*.json"))
    
    if files:
        print(f"  ✅  Replay data for {yesterday_str} already exists:")
        for f in files:
            print(f"      {f.name}")
    else:
        print(f"  ⏳  Replay data for {yesterday_str} has NOT been generated yet.")
        print(f"      Run: `make daily-report DATE={yesterday_str}`")
    print()


def main():
    print(f"\n{'='*50}")
    print(f" 🌅 MORNING CHECK  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}\n")
    
    check_containers()
    check_database()
    check_replay_status()
    
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
