"""
tests/unit/test_execution_assessor.py
Phase 12.2 — Unit tests for ExecutionAssessor.

Tests each rejection condition independently, label assignment,
tradability score range, and the full approve path.
"""
from __future__ import annotations
from dataclasses import dataclass
from uuid import uuid4

import pytest

from bot.execution.assessor import (
    ExecutionAssessor,
    _SPREAD_TIGHT_RATIO,
    _DEPTH_DEEP_MULTIPLE,
    _EXPIRY_PLENTY_MULT,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test doubles
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FakeSettings:
    """Minimal settings stand-in — mirrors the fields ExecutionAssessor uses."""
    max_spread: float = 0.08
    min_depth_usd: float = 100.0
    signal_staleness_seconds: int = 15
    min_time_to_close_mins: float = 2.0


@dataclass
class FakeFeatures:
    """Minimal SignalFeatures stand-in."""
    market_id: str
    spread: float
    total_depth_usd: float
    snapshot_age_seconds: float
    minutes_to_expiry: float


def _good_features() -> FakeFeatures:
    """All conditions clearly pass with default settings."""
    return FakeFeatures(
        market_id=f"mkt_{uuid4()}",
        spread=0.02,            # < max_spread (0.08) ✅
        total_depth_usd=300.0,  # >= min_depth (100) ✅
        snapshot_age_seconds=5, # < staleness_seconds (15) ✅
        minutes_to_expiry=30.0, # >= min_time (2.0) ✅
    )


ASSESSOR = ExecutionAssessor()
SETTINGS = FakeSettings()


# ─────────────────────────────────────────────────────────────────────────────
# Happy path — all conditions pass
# ─────────────────────────────────────────────────────────────────────────────

def test_all_conditions_pass_gives_approved():
    a = ASSESSOR.assess(_good_features(), SETTINGS)
    assert a.approved is True
    assert a.rejection_reasons == []
    assert a.tradability_score == pytest.approx(1.0)


def test_approved_assessment_has_non_empty_labels():
    a = ASSESSOR.assess(_good_features(), SETTINGS)
    assert a.spread_label != ""
    assert a.liquidity_label != ""
    assert a.staleness_label != ""
    assert a.expiry_label != ""


# ─────────────────────────────────────────────────────────────────────────────
# Individual rejection conditions
# ─────────────────────────────────────────────────────────────────────────────

def test_spread_too_wide_is_rejected():
    f = _good_features()
    f.spread = 0.09   # > max_spread (0.08)
    a = ASSESSOR.assess(f, SETTINGS)
    assert a.approved is False
    assert any("spread_too_wide" in r for r in a.rejection_reasons)

def test_spread_too_wide_reduces_score():
    f = _good_features()
    f.spread = 0.09
    a = ASSESSOR.assess(f, SETTINGS)
    # score = 0 * 0.35 + 1 * 0.30 + 1 * 0.20 + 1 * 0.15 = 0.65
    assert a.tradability_score == pytest.approx(0.65)


def test_depth_too_thin_is_rejected():
    f = _good_features()
    f.total_depth_usd = 50.0  # < min_depth (100)
    a = ASSESSOR.assess(f, SETTINGS)
    assert a.approved is False
    assert any("depth_too_thin" in r for r in a.rejection_reasons)

def test_depth_too_thin_reduces_score():
    f = _good_features()
    f.total_depth_usd = 50.0
    a = ASSESSOR.assess(f, SETTINGS)
    # score = 1*0.35 + 0*0.30 + 1*0.20 + 1*0.15 = 0.70
    assert a.tradability_score == pytest.approx(0.70)


def test_stale_snapshot_is_rejected():
    f = _good_features()
    f.snapshot_age_seconds = 20  # > staleness_seconds (15)
    a = ASSESSOR.assess(f, SETTINGS)
    assert a.approved is False
    assert any("snapshot_stale" in r for r in a.rejection_reasons)

def test_stale_snapshot_reduces_score():
    f = _good_features()
    f.snapshot_age_seconds = 20
    a = ASSESSOR.assess(f, SETTINGS)
    # score = 1*0.35 + 1*0.30 + 0*0.20 + 1*0.15 = 0.80
    assert a.tradability_score == pytest.approx(0.80)


def test_expiry_too_close_is_rejected():
    f = _good_features()
    f.minutes_to_expiry = 1.0  # < min_time (2.0)
    a = ASSESSOR.assess(f, SETTINGS)
    assert a.approved is False
    assert any("expiry_too_close" in r for r in a.rejection_reasons)

def test_expiry_too_close_reduces_score():
    f = _good_features()
    f.minutes_to_expiry = 1.0
    a = ASSESSOR.assess(f, SETTINGS)
    # score = 1*0.35 + 1*0.30 + 1*0.20 + 0*0.15 = 0.85
    assert a.tradability_score == pytest.approx(0.85)


def test_all_conditions_fail_gives_zero_score():
    f = FakeFeatures(
        market_id="fail_all",
        spread=0.10,
        total_depth_usd=10.0,
        snapshot_age_seconds=60,
        minutes_to_expiry=0.5,
    )
    a = ASSESSOR.assess(f, SETTINGS)
    assert a.approved is False
    assert len(a.rejection_reasons) == 4
    assert a.tradability_score == pytest.approx(0.0)


def test_multiple_failures_accumulate_in_reasons():
    """Two simultaneous failures → both reasons appear in the list."""
    f = _good_features()
    f.spread = 0.10        # fails
    f.total_depth_usd = 5  # fails
    a = ASSESSOR.assess(f, SETTINGS)
    assert len(a.rejection_reasons) == 2
    assert a.approved is False


# ─────────────────────────────────────────────────────────────────────────────
# Label assignment
# ─────────────────────────────────────────────────────────────────────────────

class TestSpreadLabels:
    def test_tight(self):
        f = _good_features()
        f.spread = SETTINGS.max_spread * _SPREAD_TIGHT_RATIO * 0.5   # well below tight
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.spread_label == "tight"

    def test_wide(self):
        f = _good_features()
        # between tight threshold (0.04) and max (0.08)
        f.spread = 0.06
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.spread_label == "wide"

    def test_very_wide(self):
        f = _good_features()
        f.spread = SETTINGS.max_spread + 0.01   # above max
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.spread_label == "very_wide"


class TestLiquidityLabels:
    def test_deep(self):
        f = _good_features()
        f.total_depth_usd = SETTINGS.min_depth_usd * _DEPTH_DEEP_MULTIPLE + 1
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.liquidity_label == "deep"

    def test_thin(self):
        f = _good_features()
        # >= min_depth but < 2× min_depth
        f.total_depth_usd = SETTINGS.min_depth_usd + 1.0
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.liquidity_label == "thin"

    def test_very_thin(self):
        f = _good_features()
        f.total_depth_usd = SETTINGS.min_depth_usd - 1.0
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.liquidity_label == "very_thin"


class TestStalenessLabels:
    def test_fresh(self):
        f = _good_features()
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.staleness_label == "fresh"

    def test_stale(self):
        f = _good_features()
        f.snapshot_age_seconds = SETTINGS.signal_staleness_seconds + 1
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.staleness_label == "stale"


class TestExpiryLabels:
    def test_plenty(self):
        f = _good_features()
        f.minutes_to_expiry = SETTINGS.min_time_to_close_mins * _EXPIRY_PLENTY_MULT + 1
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.expiry_label == "plenty"

    def test_near(self):
        f = _good_features()
        # between min_time and 5× min_time
        f.minutes_to_expiry = SETTINGS.min_time_to_close_mins + 0.5
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.expiry_label == "near"

    def test_critical(self):
        f = _good_features()
        f.minutes_to_expiry = SETTINGS.min_time_to_close_mins - 0.5
        a = ASSESSOR.assess(f, SETTINGS)
        assert a.expiry_label == "critical"


# ─────────────────────────────────────────────────────────────────────────────
# Score range invariant
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spread,depth,age,expiry", [
    (0.01, 300.0,  3, 60.0),   # all pass
    (0.09, 300.0,  3, 60.0),   # spread fail
    (0.01,  50.0,  3, 60.0),   # depth fail
    (0.01, 300.0, 20, 60.0),   # stale
    (0.01, 300.0,  3,  0.5),   # expiry fail
    (0.09,  50.0, 20,  0.5),   # all fail
])
def test_tradability_score_always_between_0_and_1(spread, depth, age, expiry):
    f = FakeFeatures(market_id="range_test", spread=spread,
                     total_depth_usd=depth, snapshot_age_seconds=age,
                     minutes_to_expiry=expiry)
    a = ASSESSOR.assess(f, SETTINGS)
    assert 0.0 <= a.tradability_score <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# DB round-trip: exec_tradability_score persists
# ─────────────────────────────────────────────────────────────────────────────

def test_exec_tradability_score_db_round_trip():
    """Insert a signal with exec_tradability_score and verify it persists."""
    from bot.data.repositories.signals import SignalRepository
    from bot.data.session import SessionLocal
    from bot.data.models import SignalRecord

    signal_id = f"__exec_score_test_{uuid4()}__"
    signal_dict = {
        "id": signal_id,
        "strategy_name": "eth_direction_15m_v1",
        "market_id": "__exec_score_market__",
        "token_id": "__exec_score_token__",
        "side": "BUY_YES",
        "market_prob": 0.50,
        "model_prob": 0.55,
        "edge": 0.05,
        "confidence": 0.55,
        "suggested_price": 0.51,
        "suggested_size_usd": 10.0,
        "reason": "exec score test",
        "exec_approved": True,
        "exec_reasons": "[]",
        "exec_tradability_score": 0.85,
    }

    repo = SignalRepository()
    repo.insert_signal(signal_dict)

    with SessionLocal() as session:
        record = session.get(SignalRecord, signal_id)

    assert record is not None
    assert record.exec_tradability_score == pytest.approx(0.85)
    assert record.exec_approved is True

    with SessionLocal() as session:
        row = session.get(SignalRecord, signal_id)
        if row:
            session.delete(row)
            session.commit()
