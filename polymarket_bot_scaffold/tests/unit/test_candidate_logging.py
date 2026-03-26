"""
tests/unit/test_candidate_logging.py
Phase 12.1 — Unit tests for shadow candidate logging.

Tests:
  - edge_to_bucket() at all boundaries
  - candidate_status_for_edge() logic
  - is_loggable() guard
  - CANDIDATE_FLOOR constant
  - DB round-trip: insert signal with candidate_status/edge_bucket, verify read-back
"""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from bot.analytics.candidate_buckets import (
    CANDIDATE_FLOOR,
    CANDIDATE,
    TRADEABLE,
    EDGE_BUCKET_LABELS,
    edge_to_bucket,
    candidate_status_for_edge,
    is_loggable,
)


# ─────────────────────────────────────────────────────────────────────────────
# edge_to_bucket() — boundary and mid-range tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeToBucket:
    def test_below_floor_returns_below_floor(self):
        assert edge_to_bucket(0.000) == "below_floor"
        assert edge_to_bucket(0.004) == "below_floor"
        assert edge_to_bucket(CANDIDATE_FLOOR - 0.0001) == "below_floor"

    def test_exactly_at_floor_goes_to_first_bucket(self):
        # 0.005 >= CANDIDATE_FLOOR and < 0.010 → first bucket
        assert edge_to_bucket(CANDIDATE_FLOOR) == "0.00-0.01"

    def test_first_bucket_range(self):
        assert edge_to_bucket(0.005) == "0.00-0.01"
        assert edge_to_bucket(0.009) == "0.00-0.01"

    def test_second_bucket_boundary(self):
        assert edge_to_bucket(0.010) == "0.01-0.02"
        assert edge_to_bucket(0.015) == "0.01-0.02"
        assert edge_to_bucket(0.019) == "0.01-0.02"

    def test_third_bucket(self):
        assert edge_to_bucket(0.020) == "0.02-0.03"
        assert edge_to_bucket(0.025) == "0.02-0.03"

    def test_fourth_bucket(self):
        assert edge_to_bucket(0.030) == "0.03-0.04"
        assert edge_to_bucket(0.039) == "0.03-0.04"

    def test_top_bucket_is_open_ended(self):
        assert edge_to_bucket(0.040) == "0.04+"
        assert edge_to_bucket(0.10)  == "0.04+"
        assert edge_to_bucket(0.99)  == "0.04+"

    def test_all_labels_covered(self):
        """Every EDGE_BUCKET_LABEL can be produced by edge_to_bucket."""
        midpoints = [0.005, 0.015, 0.025, 0.035, 0.050]
        produced = {edge_to_bucket(e) for e in midpoints}
        assert produced == set(EDGE_BUCKET_LABELS)


# ─────────────────────────────────────────────────────────────────────────────
# candidate_status_for_edge()
# ─────────────────────────────────────────────────────────────────────────────

class TestCandidateStatus:
    MIN_EDGE = 0.04

    def test_below_floor_returns_empty_string(self):
        assert candidate_status_for_edge(0.001, self.MIN_EDGE) == ""

    def test_between_floor_and_min_edge_is_candidate(self):
        assert candidate_status_for_edge(0.01, self.MIN_EDGE) == CANDIDATE
        assert candidate_status_for_edge(0.039, self.MIN_EDGE) == CANDIDATE

    def test_exactly_at_min_edge_is_tradeable(self):
        assert candidate_status_for_edge(self.MIN_EDGE, self.MIN_EDGE) == TRADEABLE

    def test_above_min_edge_is_tradeable(self):
        assert candidate_status_for_edge(0.06, self.MIN_EDGE) == TRADEABLE
        assert candidate_status_for_edge(0.99, self.MIN_EDGE) == TRADEABLE


# ─────────────────────────────────────────────────────────────────────────────
# is_loggable()
# ─────────────────────────────────────────────────────────────────────────────

class TestIsLoggable:
    def test_below_floor_not_loggable(self):
        assert not is_loggable(0.0)
        assert not is_loggable(CANDIDATE_FLOOR - 0.001)

    def test_at_floor_is_loggable(self):
        assert is_loggable(CANDIDATE_FLOOR)
        assert is_loggable(0.05)


# ─────────────────────────────────────────────────────────────────────────────
# EDGE_BUCKET_LABELS — ordering contract
# ─────────────────────────────────────────────────────────────────────────────

def test_edge_bucket_labels_are_ordered_and_non_empty():
    assert len(EDGE_BUCKET_LABELS) == 5
    assert EDGE_BUCKET_LABELS[0] == "0.00-0.01"
    assert EDGE_BUCKET_LABELS[-1] == "0.04+"


# ─────────────────────────────────────────────────────────────────────────────
# CANDIDATE_FLOOR value — regression guard
# ─────────────────────────────────────────────────────────────────────────────

def test_candidate_floor_value():
    """Guard: changing CANDIDATE_FLOOR invalidates historical bucket classifications."""
    assert CANDIDATE_FLOOR == pytest.approx(0.005)


# ─────────────────────────────────────────────────────────────────────────────
# DB round-trip: insert candidate signal, verify candidate_status + edge_bucket
# ─────────────────────────────────────────────────────────────────────────────

def test_candidate_signal_db_round_trip():
    """Insert a CANDIDATE row and verify both new columns persist correctly."""
    from bot.data.repositories.signals import SignalRepository
    from bot.data.session import SessionLocal
    from bot.data.models import SignalRecord

    signal_id = f"__candidate_test_{uuid4()}__"
    signal_dict = {
        "id": signal_id,
        "strategy_name": "eth_direction_15m_v1",
        "market_id": "__candidate_test_market__",
        "token_id": "__candidate_test_token__",
        "side": "BUY_YES",
        "market_prob": 0.55,
        "model_prob": 0.57,
        "edge": 0.02,
        "confidence": 0.52,
        "suggested_price": 0.56,
        "suggested_size_usd": 10.0,
        "reason": "candidate test",
        # Phase 12.1
        "candidate_status": CANDIDATE,
        "edge_bucket": "0.01-0.02",
    }

    repo = SignalRepository()
    repo.insert_signal(signal_dict)

    with SessionLocal() as session:
        record = session.get(SignalRecord, signal_id)

    assert record is not None
    assert record.candidate_status == CANDIDATE
    assert record.edge_bucket == "0.01-0.02"
    # Phase 12.0 columns should be None (not supplied)
    assert record.alpha_score is None
    assert record.exec_approved is None

    # Cleanup
    with SessionLocal() as session:
        row = session.get(SignalRecord, signal_id)
        if row:
            session.delete(row)
            session.commit()


def test_tradeable_signal_db_round_trip():
    """Insert a TRADEABLE row and verify candidate_status and edge_bucket."""
    from bot.data.repositories.signals import SignalRepository
    from bot.data.session import SessionLocal
    from bot.data.models import SignalRecord

    signal_id = f"__tradeable_test_{uuid4()}__"
    signal_dict = {
        "id": signal_id,
        "strategy_name": "eth_direction_15m_v2",
        "market_id": "__tradeable_test_market__",
        "token_id": "__tradeable_test_token__",
        "side": "BUY_NO",
        "market_prob": 0.62,
        "model_prob": 0.67,
        "edge": 0.05,
        "confidence": 0.70,
        "suggested_price": 0.38,
        "suggested_size_usd": 10.0,
        "reason": "tradeable test",
        "candidate_status": TRADEABLE,
        "edge_bucket": "0.04+",
    }

    repo = SignalRepository()
    repo.insert_signal(signal_dict)

    with SessionLocal() as session:
        record = session.get(SignalRecord, signal_id)

    assert record is not None
    assert record.candidate_status == TRADEABLE
    assert record.edge_bucket == "0.04+"

    with SessionLocal() as session:
        row = session.get(SignalRecord, signal_id)
        if row:
            session.delete(row)
            session.commit()


def test_get_candidates_by_edge_bucket_returns_all_labels():
    """get_candidates_by_edge_bucket should always return all bucket keys."""
    from bot.data.repositories.signals import SignalRepository
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    repo = SignalRepository()
    result = repo.get_candidates_by_edge_bucket(since=since)
    assert set(result.keys()) == set(EDGE_BUCKET_LABELS)
    assert all(isinstance(v, int) for v in result.values())
