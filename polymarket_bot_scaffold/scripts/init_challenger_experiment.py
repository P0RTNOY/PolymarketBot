"""
Explicitly initialize a challenger experiment for a specific market profile.
Creates the experiment manifest and a supplementary challenger_metadata.json.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.core.paths import get_profile_manifest_path
from scripts.experiment_config import compute_config_hash, write_manifest

def main():
    parser = argparse.ArgumentParser(description="Initialize a challenger experiment window.")
    parser.add_argument("--profile", required=True, help="Market profile (e.g., btc_1h_direction)")
    parser.add_argument("--label", required=True, help="Descriptive experiment label")
    parser.add_argument("--seed", type=int, default=42, help="Base seed for replay")
    parser.add_argument("--runs", type=int, default=20, help="Monte Carlo runs")
    parser.add_argument("--duration", type=int, default=7, help="Intended duration in days")
    
    args = parser.parse_args()
    
    manifest_path = get_profile_manifest_path(args.profile)
    metadata_path = manifest_path.parent / "challenger_metadata.json"
    
    # 1. Generate primary manifest (standard workflow)
    cfg_hash, cfg_dict = compute_config_hash(args.seed, args.runs, market_profile=args.profile)
    write_manifest(manifest_path, cfg_hash, cfg_dict, args.label, market_profile=args.profile)
    
    # 2. Generate supplementary challenger metadata
    start_time = datetime.now(timezone.utc).isoformat()
    metadata = {
        "market_profile": args.profile,
        "experiment_label": args.label,
        "initialized_at": start_time,
        "intended_duration_days": args.duration,
        "baseline_reference_profile": "eth_15m_direction",
        "manifest_hash": cfg_hash,
        "notes": f"Phase 12.6 challenger initialization for {args.profile}."
    }
    
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=4)
        
    print(f"\n{'='*65}")
    print(f" 🚀 CHALLENGER INITIALIZED")
    print(f" Profile          : {args.profile}")
    print(f" Label            : {args.label}")
    print(f" Start Timestamp  : {start_time}")
    print(f" Manifest Hash    : {cfg_hash}")
    print(f" Duration         : {args.duration} days")
    print(f"{'='*65}")
    
    print(f"\n 📁 Output Directory:")
    print(f" {manifest_path.parent.parent}")
    
    print(f"\n 💡 Recommended Next Steps:")
    print(f" 1. Verify collection: make challenger-check PROFILE={args.profile}")
    print(f" 2. Daily replay     : make daily-report PROFILE={args.profile} DATE=YYYY-MM-DD")
    print(f" 3. Weekly comparison: After {args.duration} days, run comparison wrapper.")
    print(f"{'='*65}\n")

if __name__ == "__main__":
    main()
