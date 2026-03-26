from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field

class MarketSnapshot(BaseModel):
    market_id: str
    token_id: str
    question: str
    best_bid: float
    best_ask: float
    midpoint: float
    spread: float
    bid_depth_usd: float
    ask_depth_usd: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None

    @classmethod
    def example(cls) -> "MarketSnapshot":
        return cls(
            market_id="market-eth-15m-1",
            token_id="token-yes-1",
            question="Will ETH be up in 15 minutes?",
            best_bid=0.67,
            best_ask=0.69,
            midpoint=0.68,
            spread=0.02,
            bid_depth_usd=250.0,
            ask_depth_usd=180.0,
        )

class TradeSignal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_name: str
    market_id: str
    token_id: str
    side: str
    market_prob: float
    model_prob: float
    edge: float
    confidence: float
    suggested_price: float
    suggested_size_usd: float
    reason: str

class OrderIntent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    mode: str
    market_id: str
    token_id: str
    side: str
    price: float
    size_usd: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# Phase 12.0 — Layered Decision Types
# These represent the three distinct concerns in the pipeline:
#   1. SignalFeatures   – raw features extracted from the market snapshot
#   2. SignalDecision   – strategy's alpha/model output
#   3. ExecutionAssessment – tradability verdict (spread, depth, staleness, expiry)
#   4. RiskAssessment   – risk/allocation verdict (position limits, daily loss, etc.)
#
# TradeSignal is kept fully intact for backward compatibility.
# The adapter module (bot/execution/adapters.py) bridges between these.
# ─────────────────────────────────────────────────────────────────────────────

class SignalFeatures(BaseModel):
    """
    Raw features extracted from a market snapshot at evaluation time.

    SCHEMA CONTRACT (stable from Phase 12.0 onwards).
    All downstream reporting phases (12.4, 12.5, 13.0) should read from
    this object rather than re-computing from raw snapshots.

    Canonical field names for reporting:
      market_prob       -- market-implied probability (midpoint)
      edge              -- model_prob - market_prob (set by the strategy at capture)
      spread            -- best_ask - best_bid
      total_depth_usd   -- total visible USD depth (bid + ask)  alias: depth
      snapshot_age_ms   -- age of the snapshot in milliseconds
    """
    market_id: str
    token_id: str
    strategy_name: str

    # ── Price features ──────────────────────────────────────────────────────
    implied_prob: float             # raw midpoint (same as market_prob; kept for compat)
    market_prob: float              # canonical alias: market-implied probability
    best_bid: float
    best_ask: float
    spread: float                   # best_ask - best_bid

    # ── Model output (captured at signal time) ───────────────────────────────
    edge: float                     # model_prob - market_prob; 0.0 before strategy fires

    # ── Depth features ──────────────────────────────────────────────────────
    bid_depth_usd: float
    ask_depth_usd: float
    total_depth_usd: float          # bid + ask  (alias: depth)
    depth_imbalance: float          # (bid - ask) / total; range [-1, 1]

    # ── Momentum ─────────────────────────────────────────────────────────────
    recent_movement: float          # current.midpoint - previous.midpoint (0 if no prev)

    # ── Time ─────────────────────────────────────────────────────────────────
    snapshot_age_seconds: float     # seconds since snapshot was taken
    snapshot_age_ms: float          # milliseconds (= seconds * 1000; convenience for reports)
    minutes_to_expiry: float        # estimated minutes remaining for the market

    # ── Extra / forward-compatible ───────────────────────────────────────────
    extra: dict[str, Any] = Field(default_factory=dict)


class SignalDecision(BaseModel):
    """The strategy's pure alpha/model output for one opportunity."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_name: str
    market_id: str
    token_id: str

    # Core prediction
    implied_prob: float             # market's implied probability
    model_prob: float               # strategy's adjusted probability
    edge: float                     # model_prob - implied_prob
    alpha_score: float              # abs(edge); used for ranking
    side: str                       # "BUY_YES" | "BUY_NO"
    confidence: float               # 0.0 – 1.0

    # Full feature snapshot attached
    features: SignalFeatures

    # Human-readable summary from strategy
    reason: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionAssessment(BaseModel):
    """Tradability verdict: can this signal be executed right now?"""
    signal_id: str
    approved: bool
    rejection_reasons: list[str] = Field(default_factory=list)

    # Simple heuristic score: 1.0 = ideal conditions, 0.0 = completely untradable
    tradability_score: float = 1.0

    # Descriptive labels for regime analysis (filled in by executor/assessor)
    spread_label: str = ""         # e.g. "tight", "wide", "very_wide"
    liquidity_label: str = ""      # e.g. "deep", "thin", "very_thin"
    expiry_label: str = ""         # e.g. "plenty", "near", "critical"
    staleness_label: str = ""      # e.g. "fresh", "stale"
    stability_label: str = ""      # e.g. "stable", "flicker", "unstable"
    stability_score: float = 0.0   # 0.0–1.0 persistence quality

    # Optional detailed metrics for logging (from Phase 12.3A)
    persistence_metrics: Any | None = None


class RiskAssessment(BaseModel):
    """Risk / allocation verdict for a SignalDecision."""
    signal_id: str
    approved: bool
    rejection_reasons: list[str] = Field(default_factory=list)

    # The final suggested size after risk adjustment (may differ from strategy suggestion)
    suggested_size_usd: float = 0.0
