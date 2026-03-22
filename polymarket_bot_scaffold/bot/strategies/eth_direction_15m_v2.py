from bot.core.config import get_settings
from bot.execution.types import MarketSnapshot, TradeSignal
from bot.strategies.base import Strategy
from datetime import datetime, timezone

class ETHDirection15mV2Strategy(Strategy):
    name = "eth_direction_15m_v2"

    def evaluate(self, current: MarketSnapshot, previous: MarketSnapshot | None) -> TradeSignal | None:
        settings = get_settings()

        # ── Filter 1: Signal freshness cutoff ──
        if current.timestamp:
            age = (datetime.now(timezone.utc) - current.timestamp.replace(tzinfo=timezone.utc)).total_seconds()
            if age > 15:
                return None

        # ── Filter 2: Spread filter ──
        if current.spread > 0.08:
            return None

        # ── Filter 3: Minimum depth threshold ──
        if current.bid_depth_usd < 100 or current.ask_depth_usd < 100:
            return None

        # ── Filter 4: Expiry no-trade zone ──
        minutes_remaining = 15.0
        if current.end_time:
            now = current.timestamp or datetime.now(timezone.utc)
            delta = current.end_time - now
            minutes_remaining = max(0.0, delta.total_seconds() / 60.0)

        if minutes_remaining < 2.0:
            return None

        # ── Core model (same v1 baseline) ──
        implied_prob = current.midpoint

        recent_movement = 0.0
        if previous:
            recent_movement = current.midpoint - previous.midpoint

        model_prob = implied_prob - (recent_movement * 0.1)

        # ── Filter 5: Order book imbalance nudge ──
        total_depth = current.bid_depth_usd + current.ask_depth_usd
        if total_depth > 0:
            imbalance = (current.bid_depth_usd - current.ask_depth_usd) / total_depth
            model_prob += imbalance * 0.03

        model_prob = max(0.01, min(0.99, model_prob))

        edge = model_prob - implied_prob

        if abs(edge) < settings.min_edge:
            return None

        side = "BUY_YES" if edge > 0 else "BUY_NO"

        # ── Filter 6: Micro-trend momentum modifier ──
        confidence = max(0.05, min(0.95, 0.50 + abs(edge)))
        if recent_movement != 0:
            trend_agrees = (recent_movement > 0 and edge > 0) or (recent_movement < 0 and edge < 0)
            if trend_agrees:
                confidence = min(0.95, confidence + 0.01)
            else:
                confidence = max(0.05, confidence - 0.01)

        suggested_price = current.best_ask if side == "BUY_YES" else max(0.01, 1.0 - current.best_bid)
        suggested_size = settings.max_order_usd
        reason = f"v2|edge={edge:.4f},move={recent_movement:.4f},rem={minutes_remaining:.1f}m,sprd={current.spread:.3f},imb={imbalance if total_depth > 0 else 0:.3f}"

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
