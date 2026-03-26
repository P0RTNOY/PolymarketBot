"""
tests/unit/test_tradability_persistence.py
Phase 12.3A — Unit tests for persistence metrics and tradability checks.
"""
import pytest
from bot.analytics.tradability_persistence import compute_persistence_metrics, is_snapshot_tradable
from bot.execution.types import SignalFeatures
from bot.core.config import Settings

@pytest.fixture
def settings():
    return Settings(
        max_spread=0.10,
        min_depth_usd=100.0,
        signal_staleness_seconds=15,
        min_time_to_close_mins=2.0,
        max_spread_jump=0.05
    )

def make_features(spread=0.02, depth=200.0, age=5.0, expiry=10.0):
    return SignalFeatures(
        market_id="m1",
        token_id="t1",
        strategy_name="test",
        implied_prob=0.5,
        market_prob=0.5,
        best_bid=0.49,
        best_ask=0.51,
        spread=spread,
        edge=0.0,
        bid_depth_usd=depth/2,
        ask_depth_usd=depth/2,
        total_depth_usd=depth,
        depth_imbalance=0.0,
        recent_movement=0.0,
        snapshot_age_seconds=age,
        snapshot_age_ms=age*1000,
        minutes_to_expiry=expiry
    )

def test_is_snapshot_tradable_pass(settings):
    f = make_features()
    assert is_snapshot_tradable(f, settings) is True

def test_is_snapshot_tradable_fail_spread(settings):
    f = make_features(spread=0.11)
    assert is_snapshot_tradable(f, settings) is False

def test_is_snapshot_tradable_fail_depth(settings):
    f = make_features(depth=50.0)
    assert is_snapshot_tradable(f, settings) is False

def test_compute_persistence_all_pass(settings):
    history = [make_features() for _ in range(5)]
    metrics = compute_persistence_metrics(history, settings)
    
    assert metrics.total_count == 5
    assert metrics.recent_tradable_ratio == 1.0
    assert metrics.consecutive_tradable_snapshots == 5
    assert metrics.spread_jump_count == 0

def test_compute_persistence_flicker_and_jumps(settings):
    # History: [OK, OK, FAIL_SPREAD, OK, OK (with jump)]
    history = [
        make_features(spread=0.02),
        make_features(spread=0.03),
        make_features(spread=0.12), # Fail
        make_features(spread=0.04),
        make_features(spread=0.11)  # Fail (spread > 0.10)
    ]
    # Update last one to be a pass but with a big jump
    history[4].spread = 0.095 # Pass (< 0.10), jump from 0.04 is 0.055 (> 0.05)
    
    metrics = compute_persistence_metrics(history, settings)
    
    assert metrics.total_count == 5
    assert metrics.stable_pass_count == 4
    assert metrics.stable_fail_count == 1
    assert metrics.recent_tradable_ratio == 0.8
    assert metrics.consecutive_tradable_snapshots == 2 # [0.02, 0.03] or [0.04, 0.095]
    assert metrics.spread_jump_count == 3 # 0.03->0.12 (0.09), 0.12->0.04 (0.08), 0.04->0.095 (0.055)

def test_compute_persistence_median_and_min(settings):
    history = [
        make_features(spread=0.01, depth=500.0),
        make_features(spread=0.05, depth=400.0),
        make_features(spread=0.10, depth=100.0)
    ]
    metrics = compute_persistence_metrics(history, settings)
    
    assert metrics.recent_spread_median == 0.05
    assert metrics.recent_spread_max == 0.10
    assert metrics.recent_depth_median == 400.0
    assert metrics.recent_depth_min == 100.0
