from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from bot.data.session import SessionLocal
from bot.data.models import SignalRecord, PaperOrder, PaperPosition, MarketSnapshot

class ReportRepository:
    def get_daily_report(self) -> dict:
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_24h = now - timedelta(hours=24)

        with SessionLocal() as session:
            # 1. Scanned markets (unique markets with a snapshot in last 24h)
            scanned = session.scalar(
                select(func.count(func.distinct(MarketSnapshot.market_id)))
                .where(MarketSnapshot.timestamp >= start_24h)
            ) or 0

            # 2. Signals generated in last 24h
            signals_24h = session.scalars(
                select(SignalRecord)
                .where(SignalRecord.timestamp >= start_24h)
            ).all()
            total_signals = len(signals_24h)

            # Rejections
            rejection_reasons = {}
            passed_risk = 0
            for sig in signals_24h:
                if sig.eval_status == "REJECTED":
                    r = sig.eval_reason or "unknown"
                    # simplify dynamic reasons (e.g. spread_too_wide(0.09) -> spread_too_wide)
                    base_r = r.split("(")[0]
                    rejection_reasons[base_r] = rejection_reasons.get(base_r, 0) + 1
                elif sig.eval_status == "ACCEPTED":
                    passed_risk += 1

            # 3. Orders placed and filled in last 24h
            orders_24h = session.scalars(
                select(PaperOrder)
                .where(PaperOrder.created_at >= start_24h)
            ).all()
            total_orders = len(orders_24h)
            filled_orders = [o for o in orders_24h if o.status == "FILLED"]
            total_filled = len(filled_orders)

            # Average fill delay
            total_delay_secs = sum(
                (o.filled_at - o.created_at).total_seconds() 
                for o in filled_orders if o.filled_at and o.created_at
            )
            avg_fill_delay_secs = (total_delay_secs / total_filled) if total_filled > 0 else 0.0

            # 4. Position metrics (Closed in 24h)
            closed_24h = session.scalars(
                select(PaperPosition)
                .where(PaperPosition.status == "CLOSED")
                .where(PaperPosition.closed_at >= start_24h)
            ).all()
            
            realized_pnl = sum(p.realized_pnl for p in closed_24h)
            best_trade = max((p.realized_pnl for p in closed_24h), default=0.0)
            worst_trade = min((p.realized_pnl for p in closed_24h), default=0.0)

            # PnL by UTC Hour
            pnl_by_hour = {}
            for p in closed_24h:
                if p.closed_at:
                    hour_str = p.closed_at.strftime("%H:00")
                    pnl_by_hour[hour_str] = pnl_by_hour.get(hour_str, 0.0) + p.realized_pnl

            # 5. Dynamic Unrealized PnL 
            open_positions = session.scalars(
                select(PaperPosition).where(PaperPosition.status == "OPEN")
            ).all()
            
            unrealized_pnl = 0.0
            for p in open_positions:
                # Find latest midpoint
                latest_snap = session.scalars(
                    select(MarketSnapshot)
                    .where(MarketSnapshot.market_id == p.market_id)
                    .where(MarketSnapshot.token_id == p.token_id)
                    .order_by(MarketSnapshot.timestamp.desc())
                    .limit(1)
                ).first()

                if latest_snap:
                    # Unrealized logic: if we hold BUY_YES, value is midpoint.
                    # Price is between 0 and 1
                    current_val = latest_snap.midpoint if p.side == "BUY_YES" else (1.0 - latest_snap.midpoint)
                    u_pnl = (current_val - p.average_entry_price) * p.size_shares
                    unrealized_pnl += u_pnl

            return {
                "markets_scanned_24h": scanned,
                "signals_generated_24h": total_signals,
                "signals_passed_risk": passed_risk,
                "rejection_reasons_summary": rejection_reasons,
                "orders_placed_24h": total_orders,
                "orders_filled_24h": total_filled,
                "average_fill_delay_secs": avg_fill_delay_secs,
                "realized_pnl_24h": realized_pnl,
                "unrealized_pnl_open": unrealized_pnl,
                "best_trade_pnl": best_trade,
                "worst_trade_pnl": worst_trade,
                "pnl_by_hour_utc": pnl_by_hour
            }
