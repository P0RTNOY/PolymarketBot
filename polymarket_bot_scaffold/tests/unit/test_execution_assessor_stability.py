"""
tests/unit/test_execution_assessor_stability.py
Phase 12.3A — Unit tests for stability-aware execution assessment.
"""
import pytest
from bot.execution.assessor import ExecutionAssessor
from bot.execution.types import SignalFeatures
from bot.core.config import Settings

@pytest.fixture
def settings():
    return Settings(
        max_spread=0.10,
        min_depth_usd=100.0,
        signal_staleness_seconds=15,
        min_time_to_close_mins=2.0,
        book_stability_lookback=5,
        book_stability_required=3,
        enable_persistence_gate=False
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

def test_assessor_stability_no_history(settings):
    assessor = ExecutionAssessor()
    f = make_features()
    assessment = assessor.assess(f, settings, history=None)
    
    assert assessment.stability_label == "stable"
    assert assessment.stability_score == 1.0
    assert assessment.approved is True

def test_assessor_stability_with_history_flicker(settings):
    assessor = ExecutionAssessor()
    f_current = make_features(spread=0.02)
    # History: 2 tradable, 3 non-tradable
    history = [
        make_features(spread=0.15), # Fail
        make_features(spread=0.15), # Fail
        make_features(spread=0.02), # Pass
        make_features(spread=0.15), # Fail
        f_current                   # Pass
    ]
    
    assessment = assessor.assess(f_current, settings, history=history)
    
    assert assessment.stability_label == "flicker"
    assert assessment.stability_score == 0.4
    # Not gated by default
    assert assessment.approved is True

def test_assessor_stability_with_history_unstable(settings):
    assessor = ExecutionAssessor()
    f_current = make_features(spread=0.15) # Current fail
    history = [make_features(spread=0.15) for _ in range(5)]
    
    assessment = assessor.assess(f_current, settings, history=history)
    
    assert assessment.stability_label == "unstable"
    assert assessment.stability_score == 0.0
    # spread_too_wide is the reason
    assert "spread_too_wide" in assessment.rejection_reasons[0]

def test_assessor_stability_gating_enabled(settings):
    settings.enable_persistence_gate = True
    assessor = ExecutionAssessor()
    
    # 2/5 stable (below required 3)
    history = [
        make_features(spread=0.15),
        make_features(spread=0.15),
        make_features(spread=0.15),
        make_features(spread=0.02),
        make_features(spread=0.02)
    ]
    f_current = history[-1]
    
    assessment = assessor.assess(f_current, settings, history=history)
    
    assert assessment.approved is False
    assert "insufficient_tradable_history" in assessment.rejection_reasons
