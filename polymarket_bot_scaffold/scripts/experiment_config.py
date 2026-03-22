"""
Experiment config fingerprinting for replay research workflows.

Computes a deterministic hash of the active configuration so that
two replay outputs can be compared for config identity.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths relative to project root ──────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent

STRATEGY_FILES = [
    _ROOT / "bot/strategies/eth_direction_15m.py",
    _ROOT / "bot/strategies/eth_direction_15m_v2.py",
    _ROOT / "bot/risk/manager.py",
    _ROOT / "bot/core/config.py",
]

FILL_MODEL_VERSION = "v2_passive_0.30"  # Bump this manually if fill logic changes
REPLAY_ENGINE_VERSION = "v2"


def _file_hash(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.md5(path.read_bytes()).hexdigest()[:12]


def compute_config_hash(seed: int | None, runs: int) -> tuple[str, dict]:
    """
    Returns (config_hash, config_dict).
    config_hash is a short hex string unique to the current configuration.
    """
    file_hashes = {f.name: _file_hash(f) for f in STRATEGY_FILES}

    # Pull risk settings through the real config object
    sys.path.insert(0, str(_ROOT))
    from bot.core.config import get_settings
    s = get_settings()
    risk_snapshot = {
        "max_open_positions":      s.max_open_positions,
        "max_notional_exposure_usd": s.max_notional_exposure_usd,
        "max_market_exposure_usd": s.max_market_exposure_usd,
        "max_daily_loss_usd":      s.max_daily_loss_usd,
        "cooldown_after_losses":   s.cooldown_after_losses,
        "cooldown_mins":           s.cooldown_mins,
        "max_spread":              s.max_spread,
        "min_depth_usd":           s.min_depth_usd,
        "min_edge":                s.min_edge,
        "signal_staleness_seconds": s.signal_staleness_seconds,
        "min_time_to_close_mins":  s.min_time_to_close_mins,
    }

    config_dict = {
        "active_strategies":      ["eth_direction_15m_v1", "eth_direction_15m_v2"],
        "fill_model_version":     FILL_MODEL_VERSION,
        "replay_engine_version":  REPLAY_ENGINE_VERSION,
        "seed":                   seed,
        "runs":                   runs,
        "risk_settings":          risk_snapshot,
        "file_hashes":            file_hashes,
    }

    # Deterministic hash of the config (excluding timestamps)
    raw = json.dumps(config_dict, sort_keys=True)
    config_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return config_hash, config_dict


def load_manifest(manifest_path: Path) -> dict | None:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return None


def is_config_mismatch(current_hash: str, manifest: dict | None) -> tuple[bool, list[str]]:
    """Returns (has_mismatch, list_of_warnings)."""
    if manifest is None:
        return False, []
    prev_hash = manifest.get("config_hash")
    if prev_hash and prev_hash != current_hash:
        warnings = [
            f"⚠  CONFIG MISMATCH — current hash ({current_hash}) differs from manifest ({prev_hash}).",
            "   This replay uses a different configuration than the frozen experiment.",
            "   Outputs will be written to a separate path to avoid contamination.",
        ]
        if manifest.get("config", {}).get("file_hashes"):
            from scripts.experiment_config import compute_config_hash
            _, current_cfg = compute_config_hash(None, 1)
            prev_hashes = manifest["config"]["file_hashes"]
            for fname, prev_h in prev_hashes.items():
                cur_h = current_cfg["file_hashes"].get(fname, "missing")
                if cur_h != prev_h:
                    warnings.append(f"   Changed: {fname} ({prev_h} → {cur_h})")
        return True, warnings
    return False, []


def write_manifest(
    manifest_path: Path,
    config_hash: str,
    config_dict: dict,
    label: str,
) -> dict:
    manifest = {
        "experiment_label": label,
        "config_hash": config_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": config_dict,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest
