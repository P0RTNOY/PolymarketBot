from datetime import datetime, timezone
from bot.core.config import get_settings
from bot.execution.types import TradeSignal

class RiskManager:
    def approve(self, signal: TradeSignal, risk_context: dict) -> tuple[bool, str]:
        s = get_settings()

        # Context unpacking
        now = risk_context.get("now", datetime.now(timezone.utc))
        daily_pnl = risk_context.get("daily_pnl", 0.0)
        consecutive_losses = risk_context.get("consecutive_losses", 0)
        last_loss_time = risk_context.get("last_loss_time")
        open_count = risk_context.get("open_count", 0)
        notional_usd = risk_context.get("notional_usd", 0.0)
        open_positions = risk_context.get("open_positions", [])

        # 1. Global Kill Switches
        if s.panic_stop:
            return False, "panic_stop_enabled"
        if not s.paper_trading_enabled and not s.live_trading_enabled:
            return False, "all_trading_disabled"

        # 2. Daily Stop Loss
        if daily_pnl <= -s.max_daily_loss_usd:
            return False, f"daily_stop_loss_hit(pnl={daily_pnl:.2f})"

        # 3. Cooldown after N losses
        if consecutive_losses >= s.cooldown_after_losses and last_loss_time:
            mins_since_loss = (now - last_loss_time.replace(tzinfo=timezone.utc)).total_seconds() / 60.0
            if mins_since_loss < s.cooldown_mins:
                return False, f"cooldown_active(consecutive={consecutive_losses}, rem={s.cooldown_mins - mins_since_loss:.1f}m)"

        # 4. Market Microstructure & Staleness
        # Note: spread and depth were moved to variables saved into the TradeSignal / DummySignal in paper_trader, or strategy.
        # However, to be purely strict at the risk level, we check them if they are propagated.
        spread = getattr(signal, "spread_at_entry", 0.0)
        if spread > s.max_spread:
            return False, f"spread_too_wide({spread:.3f})"
            
        time_rem = getattr(signal, "time_remaining_at_entry", 999.0)
        if time_rem < s.min_time_to_close_mins:
            return False, f"too_close_to_expiry({time_rem:.1f}m)"

        # 5. Position Limits
        if open_count >= s.max_open_positions:
            return False, f"max_open_positions_hit({open_count})"

        if notional_usd + signal.suggested_size_usd > s.max_notional_exposure_usd:
            return False, f"max_notional_exceeded({notional_usd:.2f})"

        market_exposure = sum(
            (p.size_shares * p.average_entry_price) 
            for p in open_positions if p.market_id == signal.market_id
        )
        if market_exposure + signal.suggested_size_usd > s.max_market_exposure_usd:
            return False, f"max_market_exposure_exceeded({market_exposure:.2f})"

        if signal.suggested_size_usd > s.max_order_usd:
            return False, f"size_above_limit({signal.suggested_size_usd:.2f})"

        if abs(signal.edge) < s.min_edge:
            return False, f"edge_below_threshold({signal.edge:.4f})"

        return True, "approved"
