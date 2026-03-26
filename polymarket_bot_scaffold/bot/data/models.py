from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Float, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from bot.data.session import Base

class Market(Base):
    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    condition_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    winning_token_id: Mapped[str | None] = mapped_column(String, nullable=True)

class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    token_id: Mapped[str] = mapped_column(String, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String, nullable=False)
    market_prob: Mapped[float] = mapped_column(Float, nullable=False)
    model_prob: Mapped[float] = mapped_column(Float, nullable=False)
    edge: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    suggested_price: Mapped[float] = mapped_column(Float, nullable=False)
    suggested_size_usd: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    eval_status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    eval_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # ── Phase 12.0 additions (nullable; existing rows stay valid) ──────────────
    # Alpha / model output
    alpha_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Execution assessment verdict
    exec_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exec_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list

    # Risk assessment verdict
    risk_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    risk_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list

    # Full SignalFeatures snapshot as JSON blob
    features_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON object

    # Phase 12.2: execution tradability score (0.0–1.0; None until assessor is run)
    exec_tradability_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Phase 12.1 additions ───────────────────────────────────────────────────────────
    # Shadow candidate status:
    #   CANDIDATE    — above floor but below min_edge (shadow-logged, never traded)
    #   TRADEABLE    — above min_edge (entered the paper-trading flow)
    #   REJECTED_EXEC — reserved for Phase 12.2
    #   REJECTED_RISK — reserved for Phase 12.2
    candidate_status: Mapped[str | None] = mapped_column(String, nullable=True)

    # Edge magnitude bucket: '0.00-0.01' | '0.01-0.02' | ... | '0.04+'
    edge_bucket: Mapped[str | None] = mapped_column(String, nullable=True)

class OutcomeToken(Base):
    __tablename__ = "outcome_tokens"

    token_id: Mapped[str] = mapped_column(String, primary_key=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    outcome_name: Mapped[str] = mapped_column(String, nullable=False)

class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    token_id: Mapped[str] = mapped_column(String, nullable=False)
    best_bid: Mapped[float] = mapped_column(Float, nullable=False)
    best_ask: Mapped[float] = mapped_column(Float, nullable=False)
    midpoint: Mapped[float] = mapped_column(Float, nullable=False)
    spread: Mapped[float] = mapped_column(Float, nullable=False)
    bid_depth_usd: Mapped[float] = mapped_column(Float, nullable=False)
    ask_depth_usd: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    signal_id: Mapped[str] = mapped_column(String, nullable=False)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    token_id: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    size_usd: Mapped[float] = mapped_column(Float, nullable=False)
    filled_size_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    strategy_version: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String, nullable=False, default="OPEN") # OPEN, PARTIAL, FILLED, CANCELED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    spread_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_remaining_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)

class PaperPosition(Base):
    __tablename__ = "paper_positions"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    token_id: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    size_shares: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_entry_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="OPEN") # OPEN, CLOSED
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
