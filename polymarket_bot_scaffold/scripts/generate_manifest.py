#!/usr/bin/env python3
"""
Generate or display the frozen experiment manifest.

Usage:
    # Create / refresh the manifest (freeze current config):
    python scripts/generate_manifest.py --label "eth_15m_v1v2_march_2026" --seed 42 --runs 20

    # Display the current manifest:
    python scripts/generate_manifest.py --show
"""
import sys
import os
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.experiment_config import compute_config_hash, write_manifest, load_manifest

MANIFEST_PATH = Path("results/manifests/experiment_manifest.json")


def cmd_show(manifest_path: Path) -> None:
    m = load_manifest(manifest_path)
    if m is None:
        print("No manifest found. Run with --label to create one.")
        return
    print(f"\n{'='*60}")
    print(f" Experiment: {m['experiment_label']}")
    print(f" Created:    {m['created_at']}")
    print(f" Hash:       {m['config_hash']}")
    print(f"{'='*60}")
    cfg = m["config"]
    print(f" Strategies: {', '.join(cfg['active_strategies'])}")
    print(f" Fill model: {cfg['fill_model_version']}")
    print(f" Replay:     {cfg['replay_engine_version']}")
    print(f" Seed:       {cfg['seed']}   Runs: {cfg['runs']}")
    print(f"\n Risk settings:")
    for k, v in cfg["risk_settings"].items():
        print(f"   {k:<30} {v}")
    print(f"\n File fingerprints:")
    for fname, fhash in cfg["file_hashes"].items():
        print(f"   {fname:<40} {fhash}")
    print()


def cmd_create(manifest_path: Path, label: str, seed: int | None, runs: int) -> None:
    config_hash, config_dict = compute_config_hash(seed, runs)

    existing = load_manifest(manifest_path)
    if existing:
        if existing["config_hash"] == config_hash:
            print(f"✅ Config unchanged (hash={config_hash}). Manifest already up to date.")
            return
        else:
            print(f"⚠  Config changed since last manifest ({existing['config_hash']} → {config_hash}).")
            print(f"   Previous label: {existing['experiment_label']}")

    manifest = write_manifest(manifest_path, config_hash, config_dict, label)
    print(f"\n{'='*60}")
    print(f" Manifest written: {manifest_path}")
    print(f" Experiment label: {label}")
    print(f" Config hash:      {config_hash}")
    print(f" Created at:       {manifest['created_at']}")
    print(f"{'='*60}\n")
    print("Config is now FROZEN. Do not modify strategy or risk files")
    print("during this experiment without re-creating the manifest.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the frozen experiment manifest.")
    parser.add_argument("--label", type=str, default=None,
                        help="Human-readable label for this experiment (required to create)")
    parser.add_argument("--seed",  type=int, default=42, help="Default RNG seed (default: 42)")
    parser.add_argument("--runs",  type=int, default=20, help="Default Monte Carlo runs (default: 20)")
    parser.add_argument("--show",  action="store_true", help="Display current manifest without modifying it")
    parser.add_argument("--manifest", type=str, default=str(MANIFEST_PATH))
    args = parser.parse_args()

    manifest_path = Path(args.manifest)

    if args.show:
        cmd_show(manifest_path)
    elif args.label:
        cmd_create(manifest_path, args.label, args.seed, args.runs)
    else:
        # Default: show if exists, else prompt
        if manifest_path.exists():
            cmd_show(manifest_path)
        else:
            print("No manifest found. Use --label 'my_experiment' to create one.")


if __name__ == "__main__":
    main()
