#!/usr/bin/env python3
"""
Daily research orchestrator for the ETH 15m paper trading experiment.

This script is the recommended daily entry point for multi-day experiment runs.
It handles:
  1. Config mismatch detection against the frozen manifest
  2. Calling the replay engine for the specified date
  3. Saving structured outputs under results/daily/ or results/weekly/
  4. Appending headline metrics to results/summaries/daily_summary.csv
  5. Printing a compact console summary

Usage:
    # Single day (recommended daily workflow):
    python scripts/run_daily_research.py --date 2026-03-22 --seed 42 --runs 20

    # Date range (weekly):
    python scripts/run_daily_research.py --start 2026-03-22 --end 2026-03-28 --seed 42 --runs 20

    # With fill probability override:
    python scripts/run_daily_research.py --date 2026-03-22 --seed 42 --runs 20 --fill-prob 0.25

    # First time: create the manifest, then run:
    python scripts/generate_manifest.py --label "eth_15m_v1v2_exp1" --seed 42 --runs 20
    python scripts/run_daily_research.py --date 2026-03-22 --seed 42 --runs 20
"""
import sys
import os
import argparse
import json
import re
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.experiment_config import (
    compute_config_hash,
    load_manifest,
    is_config_mismatch,
    FILL_MODEL_VERSION,
)
from scripts.daily_summary import append_daily_rows, print_console_summary
from scripts.replay_paper_day import run_single, load_market_resolutions, db_row_to_pydantic
from bot.core.paths import get_profile_manifest_path, get_profile_summary_path, resolve_daily_output_paths
from bot.core.config import get_settings
from bot.data.repositories.snapshots import SnapshotRepository
from bot.data.repositories.reports import ReportRepository
from bot.strategies.eth_direction_15m import ETHDirection15mStrategy
from bot.strategies.eth_direction_15m_v2 import ETHDirection15mV2Strategy

STRATEGIES = [ETHDirection15mStrategy(), ETHDirection15mV2Strategy()]
DEFAULT_PROFILE = get_settings().market_profile

import random, statistics


def _safe_filename(d: date) -> str:
    return f"replay_{d.isoformat()}"


def _safe_range_filename(start: date, end: date) -> str:
    return f"replay_{start.isoformat()}_to_{end.isoformat()}"


def resolve_out_paths_legacy(base_name: str, is_range: bool = False) -> tuple[Path, Path]:
    """Legacy helper for backward compatibility."""
    subdir = "weekly" if is_range else "daily"
    json_path = Path(f"results/{subdir}/{base_name}.json")
    csv_path  = Path(f"results/{subdir}/{base_name}.csv")
    return json_path, csv_path


def check_manifest_and_warn(config_hash: str, manifest_path: Path, profile: str) -> tuple[dict | None, str]:
    manifest = load_manifest(manifest_path)
    
    # Safety Check: Profile Mismatch
    if manifest:
        manifest_profile = manifest.get("market_profile")
        if manifest_profile and manifest_profile != profile:
            print(f"\n❌ PROFILE MISMATCH ERROR")
            print(f"   Active profile: {profile}")
            print(f"   Manifest profile: {manifest_profile}")
            print(f"   Manifest path: {manifest_path}")
            print(f"\n   To prevent data contamination, this run is ABORTING.")
            print(f"   Please use --profile {manifest_profile} or initialize a new manifest for {profile}.")
            sys.exit(1)

    mismatch, warnings = is_config_mismatch(config_hash, manifest)
    if warnings:
        print("\n" + "\n".join(warnings))
    if mismatch:
        # Append mismatch token to filenames to avoid silent overwrite
        return manifest, f"MISMATCH_{config_hash[:8]}"
    label = manifest["experiment_label"] if manifest else "no_manifest"
    return manifest, label


def run_date_range(
    start: datetime,
    end: datetime,
    seed: int | None,
    runs: int,
    fill_prob: float,
    is_range: bool,
    config_hash: str,
    config_label: str,
    **kwargs
) -> None:
    import csv as _csv

    repo = SnapshotRepository()
    resolutions = load_market_resolutions()

    raw_rows = repo.get_snapshots_in_range(start, end)
    if not raw_rows:
        print(f"⚠  No snapshots found between {start.date()} and {end.date()}.")
        return

    any_resolved = any(resolutions.get(r.market_id) for r in raw_rows)
    settlement_mode = "true+fallback" if any_resolved else "midpoint_fallback"

    token_rows: dict[str, list] = defaultdict(list)
    for row in raw_rows:
        token_rows[row.token_id].append(row)

    total_scanned = len(set(r.market_id for r in raw_rows))

    print(f"\n  📍 Markets with snapshots  : {total_scanned}")
    print(f"  📸 Snapshots loaded        : {len(raw_rows)}")
    print(f"  🪙 Unique tokens           : {len(token_rows)}")
    print(f"  🏁 Settlement mode         : {settlement_mode}\n")

    mc_pnl: dict[str, list[float]] = {s.name: [] for s in STRATEGIES}
    last_per_strategy: dict[str, dict] = {}
    all_trades: list[dict] = []

    for run_idx in range(runs):
        run_seed = (seed + run_idx) if seed is not None else None
        rng = random.Random(run_seed)
        per_strategy, trades = run_single(token_rows, resolutions, rng, fill_prob)

        for sname in mc_pnl:
            mc_pnl[sname].append(per_strategy[sname]["realized_pnl"])

        for t in trades:
            t["run"] = run_idx
            t["seed"] = run_seed
        all_trades.extend(trades)
        last_per_strategy = per_strategy

        if runs > 1:
            v1p = per_strategy["eth_direction_15m_v1"]["realized_pnl"]
            v2p = per_strategy["eth_direction_15m_v2"]["realized_pnl"]
            print(f"  run {run_idx+1:>3}/{runs}  seed={run_seed}  V1={v1p:+.4f}  V2={v2p:+.4f}")

    return mc_pnl, last_per_strategy, all_trades, settlement_mode


def save_outputs(
    base_name: str,
    is_range: bool,
    mc_pnl: dict,
    last_per_strategy: dict,
    all_trades: list,
    start: datetime,
    end: datetime,
    runs: int,
    seed: int | None,
    fill_prob: float,
    settlement_mode: str,
    config_hash: str,
    config_label: str,
    **kwargs
) -> tuple[Path, Path]:
    profile = kwargs.get("market_profile", "eth_15m_direction")
    json_path, csv_path = resolve_daily_output_paths(profile, base_name, is_range)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    # Serialise per-strategy (defaultdict → dict)
    serialisable_stats = {}
    for sname, st in last_per_strategy.items():
        serialisable_stats[sname] = {
            **{k: v for k, v in st.items() if k not in ("reject_reasons", "pnl_by_hour", "fill_delays")},
            "reject_reasons": dict(st.get("reject_reasons", {})),
            "pnl_by_hour":    dict(st.get("pnl_by_hour", {})),
            "fill_delays":    st.get("fill_delays", []),
        }

    export = {
        "meta": {
            "start":             start.isoformat(),
            "end":               end.isoformat(),
            "runs":              runs,
            "seed":              seed,
            "fill_model":        FILL_MODEL_VERSION,
            "settlement_mode":   settlement_mode,
            "market_profile":    kwargs.get("market_profile", "unknown"),
            "config_hash":       config_hash,
            "config_label":      config_label,
            "snapshots_loaded":  sum(len(t) for t in all_trades) // max(1, runs * len(last_per_strategy)),
        },
        "monte_carlo": mc_pnl,
        "last_run_stats": serialisable_stats,
        "trades": all_trades,
    }

    with open(json_path, "w") as f:
        json.dump(export, f, indent=2, default=str)

    if all_trades:
        import csv
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_trades[0].keys()))
            writer.writeheader()
            writer.writerows(all_trades)

    return json_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily research orchestrator for replay experiments.")
    parser.add_argument("--date",      type=str, default=None)
    parser.add_argument("--start",     type=str, default=None)
    parser.add_argument("--end",       type=str, default=None)
    parser.add_argument("--runs",      type=int, default=20)
    parser.add_argument("--fill-prob", type=float, default=0.30)
    parser.add_argument("--profile",   type=str, default=DEFAULT_PROFILE)
    parser.add_argument("--manifest",  type=str, default=None)
    parser.add_argument("--summary",   type=str, default=None)
    args = parser.parse_args()

    # Path resolution
    manifest_path = Path(args.manifest) if args.manifest else get_profile_manifest_path(args.profile)
    summary_path  = Path(args.summary) if args.summary else get_profile_summary_path(args.profile)

    # Parse date range
    if args.date:
        start_dt = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt   = start_dt + timedelta(days=1) - timedelta(seconds=1)
        is_range = False
        base_name = _safe_filename(start_dt.date())
    elif args.start and args.end:
        start_dt  = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt    = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(seconds=1)
        is_range  = True
        base_name = _safe_range_filename(start_dt.date(), end_dt.date())
    else:
        yesterday  = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        start_dt   = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
        end_dt     = start_dt + timedelta(days=1) - timedelta(seconds=1)
        is_range   = False
        base_name  = _safe_filename(yesterday)
        print(f"No date specified — defaulting to yesterday ({yesterday})")

    # Config fingerprint + mismatch check
    config_hash, _ = compute_config_hash(args.seed, args.runs, market_profile=args.profile)
    manifest, config_label = check_manifest_and_warn(config_hash, manifest_path, args.profile)

    # Header visibility
    print(f"\n{'━'*65}")
    print(f"  🚀 RESEARCH RUN: {args.profile.upper()}")
    print(f"  Label   : {config_label}")
    print(f"  Config  : {str(config_hash)[:12]} ({'FROZEN' if manifest_path.exists() else 'DYNAMIC'})")
    print(f"  Window  : {start_dt.date()} -> {end_dt.date()}")
    print(f"  seed={args.seed}  runs={args.runs}  fill_prob={args.fill_prob}")
    print(f"{'━'*65}\n")

    print(f"  profile     : {args.profile}")
    print(f"  config_hash : {config_hash}")
    print(f"  label       : {config_label}")

    # Check if output already exists under the same config
    json_path, csv_path = resolve_daily_output_paths(args.profile, base_name, is_range)
    if json_path.exists():
        try:
            existing_meta = json.loads(json_path.read_text()).get("meta", {})
            existing_hash = existing_meta.get("config_hash")
            if existing_hash and existing_hash != config_hash:
                print(f"\n⚠  Output file already exists with a DIFFERENT config hash.")
                print(f"   Existing: {existing_hash}  Current: {config_hash}")
                new_base = f"{base_name}_{config_hash[:8]}"
                json_path, csv_path = resolve_daily_output_paths(args.profile, new_base, is_range)
                print(f"   Writing to alternative path: {json_path}\n")
            else:
                print(f"  ℹ  Overwriting existing output (same config hash).")
        except Exception:
            pass

    result = run_date_range(
        start_dt, end_dt,
        seed=args.seed, runs=args.runs, fill_prob=args.fill_prob,
        is_range=is_range,
        config_hash=config_hash, config_label=config_label,
        market_profile=args.profile
    )
    if result is None:
        return
    mc_pnl, last_per_strategy, all_trades, settlement_mode = result

    # Phase 12.3B — Fetch Universe Quality
    reports_repo = ReportRepository()
    universe_quality = reports_repo.get_universe_quality(start=start_dt, end=end_dt)

    # Compact console summary
    print_console_summary(
        replay_date=start_dt.date(),
        mc_pnl=mc_pnl,
        last_run_stats=last_per_strategy,
        runs=args.runs,
        seed=args.seed,
        settlement_mode=settlement_mode,
        config_hash=config_hash,
        universe_quality=universe_quality,
        market_profile=args.profile,
        config_label=config_label
    )

    # Save structured outputs
    json_out, csv_out = save_outputs(
        base_name=base_name, is_range=is_range,
        mc_pnl=mc_pnl, last_per_strategy=last_per_strategy, all_trades=all_trades,
        start=start_dt, end=end_dt,
        runs=args.runs, seed=args.seed, fill_prob=args.fill_prob,
        settlement_mode=settlement_mode,
        config_hash=config_hash, config_label=config_label,
        market_profile=args.profile
    )
    print(f"  💾 JSON  : {json_out}")
    print(f"  💾 CSV   : {csv_out}")

    # Append to rolling summary
    append_daily_rows(
        replay_date=start_dt.date(),
        mc_pnl=mc_pnl,
        last_run_stats=last_per_strategy,
        runs=args.runs,
        seed=args.seed,
        settlement_mode=settlement_mode,
        config_hash=config_hash,
        config_label=config_label,
        summary_path=summary_path,
        universe_quality=universe_quality,
        market_profile=args.profile
    )
    print(f"  📋 Summary appended to: {summary_path}\n")


if __name__ == "__main__":
    main()
