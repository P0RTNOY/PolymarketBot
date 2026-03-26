#!/usr/bin/env python3
"""
scripts/check_120_columns.py
Check 1 of Phase 12.0 post-merge verification:

Confirms that newly inserted SignalRecords actually contain:
  - alpha_score     (non-null float, > 0)
  - features_json   (non-null, parseable JSON with canonical keys)
  - exec_approved   (null is OK for Phase 12.0)
  - risk_approved   (null is OK for Phase 12.0)

Also creates ONE synthetic signal via the adapter pipeline and verifies
it round-trips correctly through the DB.

Usage:
    python scripts/check_120_columns.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from bot.data.session import SessionLocal
from bot.data.models import SignalRecord
from bot.data.repositories.signals import SignalRepository
from bot.execution.types import MarketSnapshot, TradeSignal, SignalDecision
from bot.execution.adapters import build_signal_features_from_snapshot, enrich_signal_dict
from sqlalchemy import select

# ─── Canonical features_json keys that must always be present ────────────────
REQUIRED_FEATURE_KEYS = {
    "market_prob", "edge", "spread", "total_depth_usd", "snapshot_age_ms",
    "implied_prob", "best_bid", "best_ask", "depth_imbalance",
    "recent_movement", "snapshot_age_seconds", "minutes_to_expiry",
}


def check_existing_records() -> None:
    """Scan the most recent 20 signals to see Phase 12.0 column fill rate."""
    print("\n── Check 1a: existing SignalRecord column fill rate ─────────────────")
    with SessionLocal() as session:
        rows = list(session.scalars(
            select(SignalRecord).order_by(SignalRecord.timestamp.desc()).limit(20)
        ))

    if not rows:
        print("  ⚠  No signal records found — run the stack first to generate signals.")
        return

    total = len(rows)
    has_alpha = sum(1 for r in rows if r.alpha_score is not None)
    has_features = sum(1 for r in rows if r.features_json is not None)
    has_exec = sum(1 for r in rows if r.exec_approved is not None)

    print(f"  Rows inspected     : {total}")
    print(f"  alpha_score filled : {has_alpha}/{total}  {'✅' if has_alpha > 0 else '⚠  (0 — signals may predate 12.0 enrichment)'}")
    print(f"  features_json set  : {has_features}/{total}  {'✅' if has_features > 0 else '⚠  (0 — signals may predate 12.0 enrichment)'}")
    print(f"  exec_approved set  : {has_exec}/{total}  (NULL expected until Phase 12.2 — OK)")

    # Check features_json schema on filled rows
    bad_keys = []
    for r in rows:
        if r.features_json:
            try:
                parsed = json.loads(r.features_json)
                missing = REQUIRED_FEATURE_KEYS - set(parsed.keys())
                if missing:
                    bad_keys.append((r.id, missing))
            except json.JSONDecodeError as e:
                bad_keys.append((r.id, f"JSON error: {e}"))

    if bad_keys:
        print(f"  ❌ features_json schema issues found:")
        for row_id, issue in bad_keys:
            print(f"     {row_id}: {issue}")
    elif has_features > 0:
        print(f"  ✅ features_json schema valid on all {has_features} rows")


def inject_test_signal() -> None:
    """Inject one synthetic signal through the full adapter pipeline and verify the round-trip."""
    print("\n── Check 1b: synthetic signal round-trip ─────────────────────────────")

    snap = MarketSnapshot(
        market_id="__check120_market__",
        token_id="__check120_token__",
        question="Phase 12.0 column check",
        best_bid=0.60,
        best_ask=0.64,
        midpoint=0.62,
        spread=0.04,
        bid_depth_usd=300.0,
        ask_depth_usd=200.0,
        timestamp=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc) + timedelta(minutes=8),
    )

    features = build_signal_features_from_snapshot(
        strategy_name="check120_probe",
        current=snap,
        previous=None,
        edge=0.06,
    )

    signal_id = str(uuid4())
    decision = SignalDecision(
        id=signal_id,
        strategy_name="check120_probe",
        market_id=snap.market_id,
        token_id=snap.token_id,
        implied_prob=snap.midpoint,
        model_prob=snap.midpoint + 0.06,
        edge=0.06,
        alpha_score=0.06,
        side="BUY_YES",
        confidence=0.60,
        features=features,
        reason="check120|edge=0.06",
    )

    trade_signal = TradeSignal(
        id=signal_id,
        strategy_name="check120_probe",
        market_id=snap.market_id,
        token_id=snap.token_id,
        side="BUY_YES",
        market_prob=snap.midpoint,
        model_prob=snap.midpoint + 0.06,
        edge=0.06,
        confidence=0.60,
        suggested_price=snap.best_ask,
        suggested_size_usd=10.0,
        reason="check120|edge=0.06",
    )

    signal_dict = trade_signal.model_dump()
    enrich_signal_dict(signal_dict, decision=decision)

    repo = SignalRepository()
    repo.insert_signal(signal_dict)
    print(f"  Inserted synthetic signal {signal_id}")

    # Read back
    with SessionLocal() as session:
        record = session.get(SignalRecord, signal_id)

    assert record is not None, "❌ Signal not found after insert"
    assert record.alpha_score is not None, "❌ alpha_score is NULL"
    assert record.features_json is not None, "❌ features_json is NULL"

    parsed = json.loads(record.features_json)
    missing = REQUIRED_FEATURE_KEYS - set(parsed.keys())
    assert not missing, f"❌ features_json missing keys: {missing}"

    print(f"  ✅ alpha_score      : {record.alpha_score}")
    print(f"  ✅ exec_approved    : {record.exec_approved} (None expected)")
    print(f"  ✅ risk_approved    : {record.risk_approved} (None expected)")
    print(f"  ✅ features_json    : {len(record.features_json)} bytes, all {len(REQUIRED_FEATURE_KEYS)} canonical keys present")
    print(f"       market_prob    = {parsed['market_prob']}")
    print(f"       edge           = {parsed['edge']}")
    print(f"       spread         = {parsed['spread']}")
    print(f"       total_depth_usd= {parsed['total_depth_usd']}")
    print(f"       snapshot_age_ms= {parsed['snapshot_age_ms']:.1f} ms")

    # Cleanup: remove the probe row
    with SessionLocal() as session:
        row = session.get(SignalRecord, signal_id)
        if row:
            session.delete(row)
            session.commit()
    print(f"  🧹 Probe row cleaned up")


if __name__ == "__main__":
    check_existing_records()
    inject_test_signal()
    print("\n✅  Phase 12.0 column-population check complete.\n")
