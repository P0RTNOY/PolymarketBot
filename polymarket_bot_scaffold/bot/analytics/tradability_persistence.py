"""
bot/analytics/tradability_persistence.py
Phase 12.3A — Pure functions for persistent tradability analysis.
"""
from __future__ import annotations
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.execution.types import SignalFeatures
    from bot.core.config import Settings


@dataclass
class PersistenceMetrics:
    total_count: int
    stable_pass_count: int
    stable_fail_count: int
    consecutive_tradable_snapshots: int
    recent_tradable_ratio: float
    recent_spread_median: float
    recent_spread_max: float
    recent_depth_median: float
    recent_depth_min: float
    spread_jump_count: int
    stable_duration_seconds: float


def is_snapshot_tradable(f: SignalFeatures, settings: Settings) -> bool:
    """Check if a single snapshot meets microstructure requirements."""
    return (
        f.spread < settings.max_spread and
        f.total_depth_usd >= settings.min_depth_usd and
        f.snapshot_age_seconds <= settings.signal_staleness_seconds and
        f.minutes_to_expiry >= settings.min_time_to_close_mins
    )


def compute_persistence_metrics(
    history: list[SignalFeatures], settings: Settings
) -> PersistenceMetrics:
    """
    Computes tradability and stability metrics over a recent window of snapshots.
    Assumes history is sorted chronologically (oldest first).
    """
    if not history:
        return PersistenceMetrics(
            0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0
        )

    pass_count = 0
    fail_count = 0
    streak = 0
    max_streak = 0
    spreads = []
    depths = []
    jump_count = 0

    for i, f in enumerate(history):
        tradable = is_snapshot_tradable(f, settings)
        if tradable:
            pass_count += 1
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            fail_count += 1
            streak = 0

        spreads.append(f.spread)
        depths.append(f.total_depth_usd)

        # Detect spread jumps
        if i > 0:
            jump = abs(f.spread - history[i-1].spread)
            if jump > settings.max_spread_jump:
                jump_count += 1

    # Duration: time between first and last snapshot in the window
    duration = 0.0
    if len(history) > 1:
        # We don't have absolute timestamps in SignalFeatures yet, but we have 
        # the extraction context. For now, we can use the relative snapshot ages 
        # if they are consistent.
        # Actually, it's better if SignalFeatures had the raw timestamp.
        # Since it doesn't, we'll return 0 for duration for now, or 
        # update signal_engine to populate it in 'extra'.
        # Actually, SignalFeatures has snapshot_age_seconds.
        # duration = first_f.snapshot_age - last_f.snapshot_age (if chronic order)
        duration = history[0].snapshot_age_seconds - history[-1].snapshot_age_seconds
        duration = abs(duration)

    return PersistenceMetrics(
        total_count=len(history),
        stable_pass_count=pass_count,
        stable_fail_count=fail_count,
        consecutive_tradable_snapshots=max_streak,
        recent_tradable_ratio=pass_count / len(history),
        recent_spread_median=statistics.median(spreads) if spreads else 0.0,
        recent_spread_max=max(spreads) if spreads else 0.0,
        recent_depth_median=statistics.median(depths) if depths else 0.0,
        recent_depth_min=min(depths) if depths else 0.0,
        spread_jump_count=jump_count,
        stable_duration_seconds=duration,
    )
