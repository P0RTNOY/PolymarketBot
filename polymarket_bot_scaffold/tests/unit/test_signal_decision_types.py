"""
tests/unit/test_signal_decision_types.py
Phase 12.0 — Unit tests for the new layered decision types and adapters.

Tests:
1. Instantiation of SignalFeatures / SignalDecision / ExecutionAssessment / RiskAssessment
2. signal_decision_to_trade_signal adapter returns valid TradeSignal
3. enrich_signal_dict adds expected keys
4. build_signal_features_from_snapshot calculates depth/imbalance/momentum correctly
5. Existing MarketSnapshot.example() still works (regression guard)
"""
from __future__ import annotations
import json
import pytest
from datetime import datetime, timezone, timedelta

from bot.execution.types import (
    MarketSnapshot,
    TradeSignal,
    SignalFeatures,
    SignalDecision,
    ExecutionAssessment,
    RiskAssessment,
)
from bot.execution.adapters import (
    build_signal_features_from_snapshot,
    signal_decision_to_trade_signal,
    enrich_signal_dict,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        market_id="market-test-1",
        token_id="token-yes-1",
        question="Will ETH be up in 15 minutes?",
        best_bid=0.67,
        best_ask=0.69,
        midpoint=0.68,
        spread=0.02,
        bid_depth_usd=250.0,
        ask_depth_usd=180.0,
        timestamp=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


@pytest.fixture()
def sample_features(sample_snapshot) -> SignalFeatures:
    return build_signal_features_from_snapshot(
        strategy_name="test_strategy",
        current=sample_snapshot,
        previous=None,
        edge=0.04,
    )


@pytest.fixture()
def sample_decision(sample_features) -> SignalDecision:
    return SignalDecision(
        strategy_name="test_strategy",
        market_id="market-test-1",
        token_id="token-yes-1",
        implied_prob=0.68,
        model_prob=0.72,
        edge=0.04,
        alpha_score=0.04,
        side="BUY_YES",
        confidence=0.55,
        features=sample_features,
        reason="test|edge=0.04",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Type instantiation tests
# ─────────────────────────────────────────────────────────────────────────────

def test_signal_features_instantiation(sample_features: SignalFeatures) -> None:
    assert sample_features.market_id == "market-test-1"
    assert sample_features.strategy_name == "test_strategy"
    assert isinstance(sample_features.depth_imbalance, float)
    assert isinstance(sample_features.total_depth_usd, float)
    # Check stable canonical fields
    assert sample_features.market_prob == pytest.approx(sample_features.implied_prob)
    assert sample_features.edge == pytest.approx(0.04)
    assert sample_features.snapshot_age_ms == pytest.approx(sample_features.snapshot_age_seconds * 1000.0)


def test_signal_decision_instantiation(sample_decision: SignalDecision) -> None:
    assert sample_decision.strategy_name == "test_strategy"
    assert sample_decision.edge == pytest.approx(0.04)
    assert sample_decision.alpha_score == pytest.approx(0.04)
    assert isinstance(sample_decision.id, str) and len(sample_decision.id) > 0
    assert sample_decision.features is not None


def test_execution_assessment_instantiation(sample_decision: SignalDecision) -> None:
    ea = ExecutionAssessment(
        signal_id=sample_decision.id,
        approved=True,
        tradability_score=0.9,
        spread_label="tight",
        liquidity_label="deep",
        expiry_label="plenty",
        staleness_label="fresh",
    )
    assert ea.approved is True
    assert ea.rejection_reasons == []
    assert ea.tradability_score == pytest.approx(0.9)


def test_execution_assessment_rejection(sample_decision: SignalDecision) -> None:
    ea = ExecutionAssessment(
        signal_id=sample_decision.id,
        approved=False,
        rejection_reasons=["spread_too_wide", "too_close_to_expiry"],
        tradability_score=0.2,
    )
    assert ea.approved is False
    assert len(ea.rejection_reasons) == 2


def test_risk_assessment_instantiation(sample_decision: SignalDecision) -> None:
    ra = RiskAssessment(
        signal_id=sample_decision.id,
        approved=True,
        suggested_size_usd=10.0,
    )
    assert ra.approved is True
    assert ra.suggested_size_usd == pytest.approx(10.0)
    assert ra.rejection_reasons == []


# ─────────────────────────────────────────────────────────────────────────────
# Adapter tests
# ─────────────────────────────────────────────────────────────────────────────

def test_signal_decision_to_trade_signal(sample_decision: SignalDecision) -> None:
    ts = signal_decision_to_trade_signal(
        decision=sample_decision,
        suggested_price=0.69,
        suggested_size_usd=10.0,
    )
    assert isinstance(ts, TradeSignal)
    assert ts.id == sample_decision.id
    assert ts.strategy_name == "test_strategy"
    assert ts.edge == pytest.approx(0.04)
    assert ts.side == "BUY_YES"
    assert ts.suggested_price == pytest.approx(0.69)
    assert ts.suggested_size_usd == pytest.approx(10.0)


def test_enrich_signal_dict_no_assessments(sample_decision: SignalDecision) -> None:
    base_dict = {"id": sample_decision.id, "edge": 0.04}
    result = enrich_signal_dict(base_dict, decision=sample_decision)

    assert "alpha_score" in result
    assert result["alpha_score"] == pytest.approx(0.04)
    assert "features_json" in result
    features_parsed = json.loads(result["features_json"])
    assert features_parsed["market_id"] == "market-test-1"
    # Verify the canonical stable fields land in features_json
    assert "market_prob" in features_parsed
    assert "edge" in features_parsed
    assert "snapshot_age_ms" in features_parsed
    assert result["exec_approved"] is None
    assert result["risk_approved"] is None


def test_enrich_signal_dict_with_assessments(sample_decision: SignalDecision) -> None:
    base_dict = {"id": sample_decision.id}
    ea = ExecutionAssessment(
        signal_id=sample_decision.id,
        approved=False,
        rejection_reasons=["spread_too_wide"],
        tradability_score=0.3,
    )
    ra = RiskAssessment(
        signal_id=sample_decision.id,
        approved=True,
        suggested_size_usd=5.0,
    )
    result = enrich_signal_dict(base_dict, decision=sample_decision, exec_assessment=ea, risk_assessment=ra)

    assert result["exec_approved"] is False
    reasons = json.loads(result["exec_reasons"])
    assert "spread_too_wide" in reasons
    assert result["risk_approved"] is True
    assert json.loads(result["risk_reasons"]) == []


# ─────────────────────────────────────────────────────────────────────────────
# build_signal_features_from_snapshot correctness
# ─────────────────────────────────────────────────────────────────────────────

def test_depth_imbalance_calculation(sample_snapshot: MarketSnapshot) -> None:
    features = build_signal_features_from_snapshot("s", sample_snapshot, None)
    expected_imbalance = (250.0 - 180.0) / (250.0 + 180.0)
    assert features.depth_imbalance == pytest.approx(expected_imbalance, abs=1e-6)
    assert features.total_depth_usd == pytest.approx(430.0)
    assert features.recent_movement == pytest.approx(0.0)


def test_momentum_with_previous(sample_snapshot: MarketSnapshot) -> None:
    prev = MarketSnapshot(
        market_id=sample_snapshot.market_id,
        token_id=sample_snapshot.token_id,
        question="",
        best_bid=0.65,
        best_ask=0.67,
        midpoint=0.66,
        spread=0.02,
        bid_depth_usd=200.0,
        ask_depth_usd=200.0,
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=15),
    )
    features = build_signal_features_from_snapshot("s", sample_snapshot, prev)
    # 0.68 - 0.66 = 0.02
    assert features.recent_movement == pytest.approx(0.02, abs=1e-6)


def test_zero_depth_imbalance_guard() -> None:
    snap = MarketSnapshot(
        market_id="m1",
        token_id="t1",
        question="",
        best_bid=0.5,
        best_ask=0.5,
        midpoint=0.5,
        spread=0.0,
        bid_depth_usd=0.0,
        ask_depth_usd=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    features = build_signal_features_from_snapshot("s", snap, None)
    # Should not divide by zero
    assert features.depth_imbalance == pytest.approx(0.0)
    assert features.total_depth_usd == pytest.approx(0.0)


def test_snapshot_age_is_non_negative(sample_snapshot: MarketSnapshot) -> None:
    features = build_signal_features_from_snapshot("s", sample_snapshot, None)
    assert features.snapshot_age_seconds >= 0.0


def test_minutes_to_expiry_is_positive(sample_snapshot: MarketSnapshot) -> None:
    features = build_signal_features_from_snapshot("s", sample_snapshot, None)
    # Fixture has end_time = now + 10 minutes
    assert features.minutes_to_expiry > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Regression guard — existing MarketSnapshot.example() still works
# ─────────────────────────────────────────────────────────────────────────────

def test_market_snapshot_example_regression() -> None:
    snap = MarketSnapshot.example()
    assert snap.market_id == "market-eth-15m-1"
    assert snap.midpoint == pytest.approx(0.68)
