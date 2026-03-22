from sqlalchemy import select, func
from bot.data.models import PaperOrder, PaperPosition, SignalRecord
from bot.data.session import SessionLocal

class PaperRepository:
    def insert_order(self, order: dict) -> None:
        with SessionLocal() as session:
            db_order = PaperOrder(
                id=order["id"],
                signal_id=order["signal_id"],
                market_id=order["market_id"],
                token_id=order["token_id"],
                side=order["side"],
                price=order["price"],
                size_usd=order["size_usd"],
                status=order["status"],
                strategy_version=order.get("strategy_version", "unknown"),
                spread_at_entry=order.get("spread_at_entry"),
                time_remaining_at_entry=order.get("time_remaining_at_entry"),
                created_at=order.get("created_at") or __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
            )
            session.add(db_order)
            session.commit()

    def apply_fill(self, order_id: str, added_usd: float, fill_price: float, is_final: bool, filled_at=None) -> None:
        with SessionLocal() as session:
            db_order = session.get(PaperOrder, order_id)
            if db_order:
                db_order.filled_size_usd += added_usd
                
                status = "FILLED" if is_final or db_order.filled_size_usd >= db_order.size_usd else "PARTIAL"
                db_order.status = status
                
                if filled_at and status == "FILLED":
                    db_order.filled_at = filled_at
                
                # Upsert position
                stmt = select(PaperPosition).where(
                    PaperPosition.market_id == db_order.market_id,
                    PaperPosition.token_id == db_order.token_id,
                    PaperPosition.side == db_order.side,
                    PaperPosition.status == "OPEN"
                )
                pos = session.scalars(stmt).first()
                added_shares = added_usd / fill_price if fill_price > 0 else 0
                
                if pos is None:
                    new_pos = PaperPosition(
                        id=__import__('uuid').uuid4().hex,
                        market_id=db_order.market_id,
                        token_id=db_order.token_id,
                        side=db_order.side,
                        size_shares=added_shares,
                        average_entry_price=fill_price,
                    )
                    session.add(new_pos)
                else:
                    total_usd = (pos.size_shares * pos.average_entry_price) + added_usd
                    pos.size_shares += added_shares
                    if pos.size_shares > 0:
                        pos.average_entry_price = total_usd / pos.size_shares
                
                session.commit()

    def update_order_status_only(self, order_id: str, status: str) -> None:
        with SessionLocal() as session:
            db_order = session.get(PaperOrder, order_id)
            if db_order:
                db_order.status = status
                session.commit()

    def get_open_orders(self) -> list[PaperOrder]:
        with SessionLocal() as session:
            stmt = select(PaperOrder).where(PaperOrder.status.in_(["OPEN", "PARTIAL"]))
            return list(session.scalars(stmt))

    def get_positions(self) -> list[PaperPosition]:
        with SessionLocal() as session:
            stmt = select(PaperPosition)
            return list(session.scalars(stmt))

    def get_risk_context(self) -> dict:
        import datetime
        with SessionLocal() as session:
            # 1. Open positions and notional
            positions = session.scalars(select(PaperPosition).where(PaperPosition.status == "OPEN")).all()
            open_count = len(positions)
            notional = sum(p.size_shares * p.average_entry_price for p in positions)
            
            # 2. Daily realized PnL
            now = datetime.datetime.now(datetime.timezone.utc)
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            closed_today = session.scalars(
                select(PaperPosition)
                .where(PaperPosition.status == "CLOSED")
                .where(PaperPosition.closed_at >= start_of_day)
            ).all()
            daily_pnl = sum(p.realized_pnl for p in closed_today)

            # 3. Consecutive losses & last loss time
            closed_all = session.scalars(
                select(PaperPosition)
                .where(PaperPosition.status == "CLOSED")
                .order_by(PaperPosition.closed_at.desc())
                .limit(20)
            ).all()
            
            consecutive_losses = 0
            last_loss_time = None
            for p in closed_all:
                if p.realized_pnl < 0:
                    consecutive_losses += 1
                    if last_loss_time is None:
                        last_loss_time = p.closed_at
                else:
                    break # Streak broken by a win or breakeven

            return {
                "open_positions": positions,
                "open_count": open_count,
                "notional_usd": notional,
                "daily_pnl": daily_pnl,
                "consecutive_losses": consecutive_losses,
                "last_loss_time": last_loss_time,
                "now": now
            }

    def get_stats(self) -> dict:
        with SessionLocal() as session:
            # Join orders to signals to get context
            total_signals = session.scalar(select(func.count(SignalRecord.id))) or 0
            
            all_orders = session.scalars(select(PaperOrder)).all()
            total_orders = len(all_orders)
            
            filled_orders = [o for o in all_orders if o.status == "FILLED"]
            total_orders_filled = len(filled_orders)
            fill_rate = (total_orders_filled / total_orders) if total_orders > 0 else 0.0
            
            canceled_orders = [o for o in all_orders if o.status == "CANCELED"]
            cancel_rate = (len(canceled_orders) / total_orders) if total_orders > 0 else 0.0

            total_edge = 0.0
            total_spread = 0.0
            total_time_rem = 0.0
            
            edge_buckets = {
                "0.00-0.02": {"wins": 0, "losses": 0, "open": 0},
                "0.02-0.05": {"wins": 0, "losses": 0, "open": 0},
                "0.05+": {"wins": 0, "losses": 0, "open": 0}
            }
            calibration_buckets = {}
            reason_buckets = {}

            positions = self.get_positions()
            pos_dict = {(p.market_id, p.token_id, p.side): p for p in positions}

            for o in filled_orders:
                signal = session.get(SignalRecord, o.signal_id)
                if signal:
                    edge = abs(signal.edge)
                    total_edge += edge
                    
                    spread = o.spread_at_entry or 0.0
                    total_spread += spread
                    
                    time_rem = o.time_remaining_at_entry or 0.0
                    total_time_rem += time_rem
                    
                    pos = pos_dict.get((o.market_id, o.token_id, o.side))
                    if pos:
                        win_status = "open"
                        if pos.status == "CLOSED":
                            win_status = "wins" if pos.realized_pnl > 0 else "losses"
                        
                        if edge < 0.02:
                            edge_buckets["0.00-0.02"][win_status] += 1
                        elif edge < 0.05:
                            edge_buckets["0.02-0.05"][win_status] += 1
                        else:
                            edge_buckets["0.05+"][win_status] += 1
                            
                        prob_bucket = f"{int(signal.model_prob * 20) * 5}-{int(signal.model_prob * 20) * 5 + 5}%"
                        if prob_bucket not in calibration_buckets:
                            calibration_buckets[prob_bucket] = {"wins": 0, "losses": 0, "open": 0}
                        calibration_buckets[prob_bucket][win_status] += 1
                        
                        if signal.reason not in reason_buckets:
                            reason_buckets[signal.reason] = 0.0
                        
                        # Approximating PnL share if closed
                        if pos.status == "CLOSED":
                            reason_buckets[signal.reason] += (pos.realized_pnl / len([x for x in filled_orders if x.market_id == pos.market_id]))
            
            avg_edge = (total_edge / total_orders_filled) if total_orders_filled > 0 else 0.0
            avg_spread = (total_spread / total_orders_filled) if total_orders_filled > 0 else 0.0
            avg_time_rem = (total_time_rem / total_orders_filled) if total_orders_filled > 0 else 0.0
            
            closed_positions = [p for p in positions if p.status == "CLOSED"]
            total_closed = len(closed_positions)
            winning_positions = [p for p in closed_positions if p.realized_pnl > 0]
            win_rate = (len(winning_positions) / total_closed) if total_closed > 0 else 0.0
            
            realized_pnl = sum(p.realized_pnl for p in positions)
            avg_realized_pnl = (realized_pnl / total_closed) if total_closed > 0 else 0.0
            
            # Approximating holding time
            total_holding_secs = 0.0
            for p in closed_positions:
                # Find earliest order
                entry_orders = [o for o in filled_orders if o.market_id == p.market_id and o.side == p.side]
                if entry_orders:
                    earliest_fill = min((o.filled_at for o in entry_orders if o.filled_at), default=None)
                    if earliest_fill and p.closed_at:
                        delta = p.closed_at - earliest_fill
                        total_holding_secs += max(0.0, delta.total_seconds())
            
            avg_holding_time_mins = (total_holding_secs / 60.0) / total_closed if total_closed > 0 else 0.0
            
            return {
                "total_signals_generated": total_signals,
                "total_orders_filled": total_orders_filled,
                "fill_rate": fill_rate,
                "cancel_rate": cancel_rate,
                "win_rate": win_rate,
                "average_edge_at_entry": avg_edge,
                "average_spread_at_entry": avg_spread,
                "average_time_remaining_at_entry": avg_time_rem,
                "average_holding_time_mins": avg_holding_time_mins,
                "average_realized_pnl_per_trade": avg_realized_pnl,
                "total_realized_pnl": realized_pnl,
                "open_positions_count": len([p for p in positions if p.status == "OPEN"]),
                "edge_buckets": edge_buckets,
                "calibration_buckets": calibration_buckets,
                "pnl_by_reason": reason_buckets,
                "pnl_by_strategy_version": self._calc_strategy_version_stats(all_orders, positions)
            }

    @staticmethod
    def _calc_strategy_version_stats(all_orders, positions):
        pos_dict = {(p.market_id, p.token_id, p.side): p for p in positions}
        version_stats = {}
        
        for o in all_orders:
            ver = getattr(o, 'strategy_version', 'unknown') or 'unknown'
            if ver not in version_stats:
                version_stats[ver] = {"total_orders": 0, "filled": 0, "canceled": 0, "wins": 0, "losses": 0, "open": 0, "realized_pnl": 0.0}
            
            version_stats[ver]["total_orders"] += 1
            
            if o.status == "FILLED":
                version_stats[ver]["filled"] += 1
                pos = pos_dict.get((o.market_id, o.token_id, o.side))
                if pos:
                    if pos.status == "CLOSED":
                        if pos.realized_pnl > 0:
                            version_stats[ver]["wins"] += 1
                        else:
                            version_stats[ver]["losses"] += 1
                        version_stats[ver]["realized_pnl"] += pos.realized_pnl
                    else:
                        version_stats[ver]["open"] += 1
            elif o.status == "CANCELED":
                version_stats[ver]["canceled"] += 1
        
        return version_stats
