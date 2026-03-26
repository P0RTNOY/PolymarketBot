"""
bot/execution/adapters.py
Phase 12.0 — Compatibility adapters between the new layered decision types
(SignalDecision, ExecutionAssessment, RiskAssessment) and the existing
TradeSignal / signal dict format.

DESIGN PRINCIPLE:
  - Downstream consumers (PaperTrader, RiskManager, SignalRepository) still
    accept TradeSignal / dict as before.
  - These adapters translate the richer Phase 12.0 objects into the legacy
    format, so no downstream code needs to change yet.
  - In later phases, callers can migrate incrementally to use the richer types
    directly.
"""
from __future__ import annotations
import json
from bot.execution.types import (
    SignalDecision,
    ExecutionAssessment,
    RiskAssessment,
    TradeSignal,
)


def signal_decision_to_trade_signal(
    decision: SignalDecision,
    suggested_price: float,
    suggested_size_usd: float,
) -> TradeSignal:
    """
    Convert a SignalDecision into a TradeSignal for backward-compatible
    downstream use (PaperTrader, RiskManager, SignalRepository).

    Args:
        decision:         The strategy's alpha output.
        suggested_price:  Price hint from strategy (best_ask or 1-best_bid).
        suggested_size_usd: Raw size from strategy config.

    Returns:
        A TradeSignal populated from the decision fields.
    """
    return TradeSignal(
        id=decision.id,
        strategy_name=decision.strategy_name,
        market_id=decision.market_id,
        token_id=decision.token_id,
        side=decision.side,
        market_prob=decision.implied_prob,
        model_prob=decision.model_prob,
        edge=decision.edge,
        confidence=decision.confidence,
        suggested_price=suggested_price,
        suggested_size_usd=suggested_size_usd,
        reason=decision.reason,
    )


def trade_signal_to_signal_dict(signal: TradeSignal) -> dict:
    """
    Convert a TradeSignal to the dict format expected by
    SignalRepository.insert_signal().  Equivalent to signal.model_dump()
    but explicit about the contract.
    """
    return signal.model_dump()


def enrich_signal_dict(
    signal_dict: dict,
    decision: SignalDecision,
    exec_assessment: ExecutionAssessment | None = None,
    risk_assessment: RiskAssessment | None = None,
) -> dict:
    """
    Add Phase 12.0 layered fields to an existing signal dict before DB
    insertion.  All new keys map to the nullable Phase 12.0 columns added
    to SignalRecord.

    Args:
        signal_dict:     Dict produced by trade_signal_to_signal_dict().
        decision:        The SignalDecision that produced the signal.
        exec_assessment: Optional ExecutionAssessment (may be None pre-12.2).
        risk_assessment: Optional RiskAssessment (may be None pre-12.2).

    Returns:
        Updated dict (mutated in place and returned).
    """
    # Alpha / features
    signal_dict["alpha_score"] = decision.alpha_score
    signal_dict["features_json"] = json.dumps(decision.features.model_dump())

    # Execution assessment
    if exec_assessment is not None:
        signal_dict["exec_approved"] = exec_assessment.approved
        signal_dict["exec_reasons"] = json.dumps(exec_assessment.rejection_reasons)
        signal_dict["exec_tradability_score"] = exec_assessment.tradability_score
        signal_dict["exec_stability_score"] = exec_assessment.stability_score
        signal_dict["exec_stability_label"] = exec_assessment.stability_label
        
        # Persistence metrics (Phase 12.3A)
        if exec_assessment.persistence_metrics:
            p = exec_assessment.persistence_metrics
            signal_dict["exec_recent_tradable_ratio"] = p.recent_tradable_ratio
            signal_dict["exec_consecutive_tradable_snapshots"] = p.consecutive_tradable_snapshots
            signal_dict["exec_stable_duration_seconds"] = p.stable_duration_seconds
            # We add persistence reasons to the main exec_reasons JSON list in assessor, 
            # but we can also store them separately if needed. 
            # For now, let's just make sure they are in the dict.
            signal_dict["exec_stability_reasons"] = json.dumps(exec_assessment.rejection_reasons)
        else:
            signal_dict["exec_recent_tradable_ratio"] = None
            signal_dict["exec_consecutive_tradable_snapshots"] = None
            signal_dict["exec_stable_duration_seconds"] = None
            signal_dict["exec_stability_reasons"] = None
    else:
        signal_dict["exec_approved"] = None
        signal_dict["exec_reasons"] = None
        signal_dict["exec_tradability_score"] = None
        signal_dict["exec_stability_score"] = None
        signal_dict["exec_stability_label"] = None
        signal_dict["exec_recent_tradable_ratio"] = None
        signal_dict["exec_consecutive_tradable_snapshots"] = None
        signal_dict["exec_stable_duration_seconds"] = None
        signal_dict["exec_stability_reasons"] = None

    # Risk assessment
    if risk_assessment is not None:
        signal_dict["risk_approved"] = risk_assessment.approved
        signal_dict["risk_reasons"] = json.dumps(risk_assessment.rejection_reasons)
    else:
        signal_dict["risk_approved"] = None
        signal_dict["risk_reasons"] = None

    return signal_dict


def build_signal_features_from_snapshot(
    strategy_name: str,
    current,  # bot.execution.types.MarketSnapshot
    previous,  # bot.execution.types.MarketSnapshot | None
    edge: float = 0.0,  # from strategy output; defaults to 0.0 before strategy fires
) -> "SignalFeatures":  # noqa: F821 — resolved at runtime
    """
    Convenience factory: build a SignalFeatures from a current/previous
    MarketSnapshot pair.  Called by signal_engine after strategy.evaluate();
    pass the actual edge value so features_json is self-describing.
    """
    from datetime import datetime, timezone
    from bot.execution.types import SignalFeatures

    now = datetime.now(timezone.utc)

    # Snapshot age
    snap_ts = current.timestamp
    if snap_ts is not None:
        if snap_ts.tzinfo is None:
            snap_ts = snap_ts.replace(tzinfo=timezone.utc)
        age_seconds = (now - snap_ts).total_seconds()
    else:
        age_seconds = 0.0

    # Time to expiry
    if current.end_time is not None:
        ref = current.timestamp or now
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        end = current.end_time
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        minutes_to_expiry = max(0.0, (end - ref).total_seconds() / 60.0)
    else:
        minutes_to_expiry = 15.0

    # Depth imbalance
    total_depth = current.bid_depth_usd + current.ask_depth_usd
    depth_imbalance = (
        (current.bid_depth_usd - current.ask_depth_usd) / total_depth
        if total_depth > 0
        else 0.0
    )

    # Momentum
    recent_movement = 0.0
    if previous is not None:
        recent_movement = current.midpoint - previous.midpoint

    return SignalFeatures(
        market_id=current.market_id,
        token_id=current.token_id,
        strategy_name=strategy_name,
        implied_prob=current.midpoint,
        market_prob=current.midpoint,       # canonical alias
        best_bid=current.best_bid,
        best_ask=current.best_ask,
        spread=current.spread,
        edge=edge,                           # from strategy output
        bid_depth_usd=current.bid_depth_usd,
        ask_depth_usd=current.ask_depth_usd,
        total_depth_usd=total_depth,
        depth_imbalance=depth_imbalance,
        recent_movement=recent_movement,
        snapshot_age_seconds=age_seconds,
        snapshot_age_ms=age_seconds * 1000.0,
        minutes_to_expiry=minutes_to_expiry,
    )
