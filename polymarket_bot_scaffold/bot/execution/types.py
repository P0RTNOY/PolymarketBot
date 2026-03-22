from __future__ import annotations
from datetime import datetime, timezone
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
