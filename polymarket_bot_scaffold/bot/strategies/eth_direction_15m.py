from math import exp
from bot.core.config import get_settings
from bot.execution.types import MarketSnapshot, TradeSignal
from bot.strategies.base import Strategy

class ETHDirection15mStrategy(Strategy):
    name = "eth_direction_15m_v1"

    def evaluate(self, current: MarketSnapshot, previous: MarketSnapshot | None) -> TradeSignal | None:
        settings = get_settings()
        
        # Calculate recent movement (dumb baseline)
        recent_movement = 0.0
        if previous:
            recent_movement = current.midpoint - previous.midpoint

        implied_prob = current.midpoint
        
        # Calculate time remaining in minutes
        minutes_remaining = 15.0 # Default
        if current.end_time:
            now = current.timestamp or __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
            delta = current.end_time - now
            minutes_remaining = max(0.0, delta.total_seconds() / 60.0)

        # Crude model baseline: 
        # If price moved up recently, we stubbornly expect it to revert slightly (-0.1 * movement)
        # This is purely a dummy baseline to prove the signal engine can compute an edge vs market.
        model_prob = implied_prob - (recent_movement * 0.1)
        model_prob = max(0.01, min(0.99, model_prob))

        edge = model_prob - implied_prob
        
        # Only trade if there's sufficient time and edge > threshold
        if minutes_remaining < 1.0 or abs(edge) < settings.min_edge:
            return None

        side = "BUY_YES" if edge > 0 else "BUY_NO"
        confidence = max(0.05, min(0.95, 0.50 + abs(edge)))
        suggested_price = current.best_ask if side == "BUY_YES" else max(0.01, 1.0 - current.best_bid)
        suggested_size = settings.max_order_usd
        reason = f"edge={edge:.4f}, move={recent_movement:.4f}, rem={minutes_remaining:.1f}m"

        return TradeSignal(
            strategy_name=self.name,
            market_id=current.market_id,
            token_id=current.token_id,
            side=side,
            market_prob=implied_prob,
            model_prob=model_prob,
            edge=edge,
            confidence=confidence,
            suggested_price=suggested_price,
            suggested_size_usd=suggested_size,
            reason=reason,
        )
