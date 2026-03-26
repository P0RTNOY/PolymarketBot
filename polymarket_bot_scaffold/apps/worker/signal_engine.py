"""
apps/worker/signal_engine.py
Phase 12.1 — Signal engine with shadow candidate logging.

Architecture:
  For every active market × every strategy, the engine now runs a two-pass
  evaluation:

  PASS 1 — Raw feature extraction (always runs):
    Compute SignalFeatures from the current/previous snapshot pair.
    Compute raw edge from v1/v2 model logic directly (without the min_edge gate).
    Log the opportunity to DB as CANDIDATE or TRADEABLE.

  PASS 2 — Trade placement (only if edge >= min_edge):
    Call strategy.evaluate() as before.
    Build SignalDecision, enrich signal dict, insert TRADEABLE signal, hand off
    to paper trader via existing flow.

This design means:
  - All opportunities above CANDIDATE_FLOOR are logged.
  - The min_edge gate for actual trades is completely unchanged.
  - v1/v2 strategy classes are not modified.
"""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from bot.core.config import get_settings
from bot.execution.types import MarketSnapshot, SignalDecision
from bot.execution.adapters import (
    build_signal_features_from_snapshot,
    enrich_signal_dict,
)
from bot.execution.assessor import ExecutionAssessor
from bot.analytics.candidate_buckets import (
    CANDIDATE_FLOOR,
    CANDIDATE,
    TRADEABLE,
    edge_to_bucket,
    candidate_status_for_edge,
    is_loggable,
)
from bot.strategies.eth_direction_15m import ETHDirection15mStrategy
from bot.strategies.eth_direction_15m_v2 import ETHDirection15mV2Strategy
from bot.data.repositories.markets import MarketRepository
from bot.data.repositories.snapshots import SnapshotRepository
from bot.data.repositories.signals import SignalRepository


# ─────────────────────────────────────────────────────────────────────────────
# Raw edge estimator
# Called BEFORE strategy.evaluate() to get the unfiltered edge so we can log
# below-threshold candidates.  Mirrors the core model logic of each strategy
# without any filtering.
# ─────────────────────────────────────────────────────────────────────────────

def _raw_edge_v1(current: MarketSnapshot, previous: MarketSnapshot | None) -> tuple[float, float, str]:
    """
    Compute raw (model_prob, edge, side) using v1 model logic, no filters.
    Returns (model_prob, edge, side).
    """
    recent_movement = 0.0
    if previous:
        recent_movement = current.midpoint - previous.midpoint
    implied_prob = current.midpoint
    model_prob = implied_prob - (recent_movement * 0.1)
    model_prob = max(0.01, min(0.99, model_prob))
    edge = model_prob - implied_prob
    side = "BUY_YES" if edge > 0 else "BUY_NO"
    return model_prob, edge, side


def _raw_edge_v2(current: MarketSnapshot, previous: MarketSnapshot | None) -> tuple[float, float, str]:
    """
    Compute raw (model_prob, edge, side) using v2 model logic, no filters.
    Returns (model_prob, edge, side).
    """
    recent_movement = 0.0
    if previous:
        recent_movement = current.midpoint - previous.midpoint
    implied_prob = current.midpoint
    model_prob = implied_prob - (recent_movement * 0.1)
    total_depth = current.bid_depth_usd + current.ask_depth_usd
    imbalance = 0.0
    if total_depth > 0:
        imbalance = (current.bid_depth_usd - current.ask_depth_usd) / total_depth
    model_prob += imbalance * 0.03
    model_prob = max(0.01, min(0.99, model_prob))
    edge = model_prob - implied_prob
    side = "BUY_YES" if edge > 0 else "BUY_NO"
    return model_prob, edge, side


# Map strategy name → raw edge function
_RAW_EDGE_FN = {
    "eth_direction_15m_v1": _raw_edge_v1,
    "eth_direction_15m_v2": _raw_edge_v2,
}


def _build_candidate_signal_dict(
    *,
    signal_id: str,
    strategy_name: str,
    current: MarketSnapshot,
    model_prob: float,
    edge: float,
    side: str,
    features,
    candidate_status: str,
    edge_bucket: str,
    suggested_size_usd: float,
) -> dict:
    """Build a signal dict for a below-threshold candidate."""
    suggested_price = current.best_ask if side == "BUY_YES" else max(0.01, 1.0 - current.best_bid)
    confidence = max(0.05, min(0.95, 0.50 + abs(edge)))
    reason = f"candidate|edge={edge:.4f},status={candidate_status}"

    decision = SignalDecision(
        id=signal_id,
        strategy_name=strategy_name,
        market_id=current.market_id,
        token_id=current.token_id,
        implied_prob=current.midpoint,
        model_prob=model_prob,
        edge=edge,
        alpha_score=abs(edge),
        side=side,
        confidence=confidence,
        features=features,
        reason=reason,
    )

    signal_dict = {
        "id": signal_id,
        "strategy_name": strategy_name,
        "market_id": current.market_id,
        "token_id": current.token_id,
        "side": side,
        "market_prob": current.midpoint,
        "model_prob": model_prob,
        "edge": edge,
        "confidence": confidence,
        "suggested_price": suggested_price,
        "suggested_size_usd": suggested_size_usd,
        "reason": reason,
    }

    enrich_signal_dict(signal_dict, decision=decision)
    signal_dict["candidate_status"] = candidate_status
    signal_dict["edge_bucket"] = edge_bucket
    return signal_dict


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    settings = get_settings()
    strategies = [ETHDirection15mStrategy(), ETHDirection15mV2Strategy()]
    market_repo = MarketRepository()
    snapshot_repo = SnapshotRepository()
    signal_repo = SignalRepository()

    print("[signal_engine] started")
    print(f"[signal_engine] running {len(strategies)} strategies: {[s.name for s in strategies]}")


    while True:
        try:
            markets = market_repo.list_markets()
            active_markets = [m for m in markets if m.active and not m.closed]

            for m in active_markets:
                history = snapshot_repo.get_snapshot_history(m.id, limit=2)
                if not history:
                    continue

                current_db = history[0]
                prev_db = history[1] if len(history) > 1 else None

                current_exec = MarketSnapshot(
                    market_id=current_db.market_id,
                    token_id=current_db.token_id,
                    question=m.question,
                    best_bid=current_db.best_bid,
                    best_ask=current_db.best_ask,
                    midpoint=current_db.midpoint,
                    spread=current_db.spread,
                    bid_depth_usd=current_db.bid_depth_usd,
                    ask_depth_usd=current_db.ask_depth_usd,
                    timestamp=current_db.timestamp,
                    end_time=m.end_time
                )

                prev_exec = None
                if prev_db:
                    prev_exec = MarketSnapshot(
                        market_id=prev_db.market_id,
                        token_id=prev_db.token_id,
                        question=m.question,
                        best_bid=prev_db.best_bid,
                        best_ask=prev_db.best_ask,
                        midpoint=prev_db.midpoint,
                        spread=prev_db.spread,
                        bid_depth_usd=prev_db.bid_depth_usd,
                        ask_depth_usd=prev_db.ask_depth_usd,
                        timestamp=prev_db.timestamp,
                        end_time=m.end_time
                    )

                for strategy in strategies:
                    # ── Phase 12.1: PASS 1 — raw edge pre-computation ──────────
                    # Compute edge WITHOUT the min_edge gate so we can log
                    # below-threshold candidates.
                    raw_fn = _RAW_EDGE_FN.get(strategy.name)
                    if raw_fn is None:
                        # Unknown strategy: fall through to existing evaluate() path
                        raw_model_prob, raw_edge, raw_side = None, None, None
                    else:
                        try:
                            raw_model_prob, raw_edge, raw_side = raw_fn(current_exec, prev_exec)
                        except Exception as raw_err:
                            print(f"[signal_engine] [raw_edge warn] {strategy.name}: {raw_err}")
                            raw_model_prob, raw_edge, raw_side = None, None, None

                    abs_raw_edge = abs(raw_edge) if raw_edge is not None else 0.0

                    # ── Phase 12.1: below-threshold candidate logging ─────────
                    if (
                        raw_edge is not None
                        and is_loggable(abs_raw_edge)
                        and abs_raw_edge < settings.min_edge
                    ):
                        try:
                            cstatus = CANDIDATE
                            ebucket = edge_to_bucket(abs_raw_edge)
                            features = build_signal_features_from_snapshot(
                                strategy_name=strategy.name,
                                current=current_exec,
                                previous=prev_exec,
                                edge=raw_edge,
                            )
                            # Phase 12.2: assess execution quality for candidate
                            exec_assessment = ExecutionAssessor().assess(features, settings)
                            candidate_dict = _build_candidate_signal_dict(
                                signal_id=str(uuid4()),
                                strategy_name=strategy.name,
                                current=current_exec,
                                model_prob=raw_model_prob,
                                edge=raw_edge,
                                side=raw_side,
                                features=features,
                                candidate_status=cstatus,
                                edge_bucket=ebucket,
                                suggested_size_usd=settings.max_order_usd,
                            )
                            enrich_signal_dict(
                                candidate_dict,
                                decision=SignalDecision(
                                    id=candidate_dict["id"],
                                    strategy_name=strategy.name,
                                    market_id=current_exec.market_id,
                                    token_id=current_exec.token_id,
                                    implied_prob=current_exec.midpoint,
                                    model_prob=raw_model_prob,
                                    edge=raw_edge,
                                    alpha_score=abs_raw_edge,
                                    side=raw_side,
                                    confidence=max(0.05, min(0.95, 0.5 + abs_raw_edge)),
                                    features=features,
                                    reason=f"candidate|edge={raw_edge:.4f}",
                                ),
                                exec_assessment=exec_assessment,
                            )
                            candidate_dict["candidate_status"] = cstatus
                            candidate_dict["edge_bucket"] = ebucket
                            signal_repo.insert_signal(candidate_dict)
                            print(
                                f"[signal_engine] [{strategy.name}] CANDIDATE "
                                f"{m.id} | edge={raw_edge:.4f} bucket={ebucket} "
                                f"exec={'OK' if exec_assessment.approved else 'FAIL'} "
                                f"score={exec_assessment.tradability_score:.2f}"
                            )
                        except Exception as cand_err:
                            print(f"[signal_engine] [candidate warn] {cand_err}")

                    # ── PASS 2: existing trade-approval flow (unchanged) ──────
                    signal = strategy.evaluate(current_exec, prev_exec)
                    if signal:
                        signal_dict = signal.model_dump()

                        # Phase 12.0 + 12.2 enrichment
                        try:
                            features = build_signal_features_from_snapshot(
                                strategy_name=strategy.name,
                                current=current_exec,
                                previous=prev_exec,
                                edge=signal.edge,
                            )
                            decision = SignalDecision(
                                id=signal.id,
                                strategy_name=signal.strategy_name,
                                market_id=signal.market_id,
                                token_id=signal.token_id,
                                implied_prob=signal.market_prob,
                                model_prob=signal.model_prob,
                                edge=signal.edge,
                                alpha_score=abs(signal.edge),
                                side=signal.side,
                                confidence=signal.confidence,
                                features=features,
                                reason=signal.reason,
                            )
                            # Phase 12.2: assess execution quality (observational only)
                            exec_assessment = ExecutionAssessor().assess(features, settings)
                            enrich_signal_dict(
                                signal_dict,
                                decision=decision,
                                exec_assessment=exec_assessment,
                                risk_assessment=None,
                            )
                        except Exception as enrich_err:
                            print(f"[signal_engine] [12.0 enrich warn] {enrich_err}")

                        # Phase 12.1: mark as TRADEABLE
                        signal_dict["candidate_status"] = TRADEABLE
                        signal_dict["edge_bucket"] = edge_to_bucket(abs(signal.edge))

                        signal_repo.insert_signal(signal_dict)
                        print(
                            f"[signal_engine] [{strategy.name}] TRADEABLE signal for "
                            f"{m.id} | side={signal.side} edge={signal.edge:.4f}"
                        )

            await asyncio.sleep(5)

        except Exception as e:
            print("[signal_engine] ERROR:", str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
